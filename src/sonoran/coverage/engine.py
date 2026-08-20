"""The SPLAT! coverage engine, outside the browser.

The engine is the ITM / Longley-Rice model from SPLAT! by John A.
Magliacane, KD2BD, compiled to WebAssembly by the Meshtastic Site
Planner project. It is vendored without change in
`web/static/vendor/splat/`, under the GNU General Public License,
version 3. See `AGENTS.md` 7.1.

The planner page runs that file in a browser worker. This module runs
the same file in Python. That is the point of it: one binary answers
both, so the page a person plans with and the map the mesh publishes
cannot predict different things.

The module is a plain computation. It imports three functions and
nothing else, and it asks for no files, no clock, and no network:

    __cxa_throw(i32, i32, i32) -> void
    abort_js() -> void
    emscripten_resize_heap(i32) -> i32

`web/static/planner.worker.js` is the same wrapper in JavaScript. Read
both together when either changes.

One trap is different here. `AGENTS.md` 9.16 says a heap view goes
stale after any call that grows the heap. That is a JavaScript problem,
because `HEAPU8` is a cached view. This module reads and writes memory
through `wasmtime` each time and caches nothing, so the trap cannot
happen. Do not add a cached pointer to make it faster.

The other trap is the same in both languages. Every allocation needs a
free. `_scratch` is a context manager for that reason, and there is no
way to allocate without one.
"""

import struct
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import wasmtime

from sonoran.coverage.params import EngineParams
from sonoran.coverage.units import metres_to_feet
from sonoran.logging import get_logger

logger = get_logger(__name__)

# The engine file, beside the loader the browser uses.
WASM_PATH = (
    Path(__file__).parent.parent / "web" / "static" / "vendor" / "splat" / "splat_driver.wasm"
)

# What each negative return code means.
ENGINE_ERRORS: dict[int, str] = {
    -1: "out of memory",
    -2: "bad handle",
    -3: "bad page",
    -4: "coverage region too large",
    -5: "invalid parameters",
}

# The compiled export names. The build minifies them to single letters.
# `web/static/vendor/splat/splat_driver.mjs` holds the same mapping and
# is the source of this list.
_EXPORTS: dict[str, str] = {
    "__wasm_call_ctors": "e",
    "splat_create": "f",
    "splat_page_count": "g",
    "splat_page_info": "h",
    "splat_load_page": "i",
    "splat_radial_count": "j",
    "splat_run_radials": "k",
    "splat_rasterize": "l",
    "splat_region_info": "m",
    "splat_signal_ptr": "n",
    "splat_mask_ptr": "o",
    "splat_errnum_counts": "p",
    "splat_point_to_point": "q",
    "splat_p2p_profile_ptr": "r",
    "splat_highpoint": "s",
    "splat_destroy": "t",
    "splat_malloc": "u",
    "splat_free": "v",
}

_MEMORY_EXPORT = "d"

# One page of WebAssembly memory, in bytes.
_PAGE_BYTES = 65536

# The largest heap the engine may grow to, in bytes.
#
# The browser loader sets the same ceiling. A run that asks for more has
# a radius or a resolution that is wrong, and letting it grow would take
# the whole container down instead of failing one prediction.
MAX_HEAP_BYTES = 1024 * 1024 * 1024

# Cells in one elevation page, on each side.
#
# The terrain service serves pages of this size only. See
# `sonoran/terrain/srtm.py`.
PAGE_SIZE = 1200

# The number of ITM warning codes the engine counts.
ERRNUM_COUNT = 6

# The bits of a mask byte that mean "this cell was reached".
#
# The low three bits are not a coverage flag, which is why the test is
# against 248 and not against zero.
MASK_COVERED = 0b1111_1000


class EngineError(RuntimeError):
    """The engine refused a call."""

    def __init__(self, code: int, what: str) -> None:
        meaning = ENGINE_ERRORS.get(code, f"engine error {code}")
        super().__init__(f"{what}: {meaning}")
        self.code = code


@dataclass(frozen=True)
class PageRef:
    """The south-west corner of one elevation page the engine wants.

    `min_west` counts degrees west and is always positive, which is how
    SPLAT! names a place. Use `signed_longitude` to get back to the
    longitude everything else uses.
    """

    min_north: int
    min_west: int

    @property
    def signed_longitude(self) -> int:
        """Return the west edge as a signed longitude."""
        return -(self.min_west + 1) if self.min_west < 180 else 359 - self.min_west

    @property
    def tile_name(self) -> str:
        """Return the SRTM tile name that holds this page."""
        latitude = self.min_north
        longitude = self.signed_longitude
        north_south = "N" if latitude >= 0 else "S"
        east_west = "E" if longitude >= 0 else "W"
        return f"{north_south}{abs(latitude):02d}{east_west}{abs(longitude):03d}"


@dataclass(frozen=True)
class Region:
    """The ground one raster covers.

    The engine works in whole degrees, so the region is far larger than
    the radius the run asked for.
    """

    width: int
    height: int
    north: float
    south: float
    east: float
    west: float
    radials: int
    pages: int


@dataclass(frozen=True)
class ProfilePoint:
    """One point on the ground under a link."""

    distance_km: float
    ground_m: float


@dataclass(frozen=True)
class Link:
    """One path from the transmitter to a place.

    `itm_errno` above zero means the model had a complaint about this
    path. Say so rather than hiding it.
    """

    loss_db: float
    dbm: float
    distance_km: float
    azimuth_deg: float
    itm_errno: int
    profile: list[ProfilePoint] = field(default_factory=list)


@dataclass(frozen=True)
class Raster:
    """What one run computed.

    `signal` holds the field strength of each cell as a byte with a
    200 dB offset. `mask` says which cells the sweep reached. A cell
    that was never reached has no value at all, so read `mask` first.
    """

    region: Region
    signal: bytes
    mask: bytes
    errnum_counts: tuple[int, ...]

    def dbm_at(self, index: int) -> float | None:
        """Return the field of one cell in dBm, or None if never reached."""
        if not self.mask[index] & MASK_COVERED:
            return None
        return self.signal[index] - 200.0


class SplatModule:
    """The compiled engine, read once.

    Reading and compiling the file costs more than a prediction does, so
    a process that makes many predictions must hold one of these.
    """

    def __init__(self, wasm_path: Path = WASM_PATH) -> None:
        self._engine = wasmtime.Engine()
        self._module = wasmtime.Module.from_file(self._engine, str(wasm_path))
        logger.debug("compiled the coverage engine from %s", wasm_path)

    def instance(self) -> "SplatInstance":
        """Return a new instance with its own memory.

        One instance serves any number of predictions. `run` creates
        and destroys the prediction inside it, so a process that makes
        many of them wants one instance and not one for each. See
        `AGENTS.md` 9.16.4.
        """
        return SplatInstance(self._engine, self._module)


class SplatInstance:
    """One instance of the engine, with its own linear memory.

    An instance is not safe to share between threads. Give each worker
    its own, and give it only one: an instance is made for a process
    and not for a prediction. See `AGENTS.md` 9.16.4.

    The linear memory grows to the largest run the instance has made
    and never shrinks, which is the point of holding one: the second
    run on it costs no more memory.

    A new instance for each prediction grows a new heap each time, and
    the old ones are never given back. `close` is the only way to give
    one back. See `AGENTS.md` 9.16.4.
    """

    def __init__(self, engine: wasmtime.Engine, module: wasmtime.Module) -> None:
        self._store = wasmtime.Store(engine)
        # The memory is exported, so it does not exist until the module
        # is instantiated. `emscripten_resize_heap` needs it, so it is
        # read from this attribute and not captured.
        self._memory: wasmtime.Memory | None = None

        linker = wasmtime.Linker(engine)
        linker.define_func(
            "a", "a", wasmtime.FuncType([wasmtime.ValType.i32()] * 3, []), self._throw
        )
        linker.define_func("a", "b", wasmtime.FuncType([], []), self._abort)
        linker.define_func(
            "a",
            "c",
            wasmtime.FuncType([wasmtime.ValType.i32()], [wasmtime.ValType.i32()]),
            self._resize_heap,
        )

        instance = linker.instantiate(self._store, module)
        exports = instance.exports(self._store)

        memory = exports[_MEMORY_EXPORT]
        assert isinstance(memory, wasmtime.Memory)
        self._memory = memory

        self._functions: dict[str, wasmtime.Func] = {}
        for name, symbol in _EXPORTS.items():
            function = exports[symbol]
            assert isinstance(function, wasmtime.Func)
            self._functions[name] = function

        # C++ static constructors. Nothing works before this runs.
        self._functions["__wasm_call_ctors"](self._store)

    def close(self) -> None:
        """Give the linear memory back now.

        The store holds the three host functions, which are bound
        methods of this object, so the store and this object hold each
        other. Dropping the name does not free the heap, and neither
        does the cyclic collector: it counts objects, and a heap of
        several hundred megabytes is not one. Clearing the references
        here breaks the cycle and gives the memory back at once.

        The instance cannot be used afterwards.
        """
        self._functions = {}
        self._memory = None
        del self._store

    def __enter__(self) -> "SplatInstance":
        return self

    def __exit__(self, *_exception: object) -> None:
        self.close()

    # --- the three imports ---------------------------------------------

    def _throw(self, pointer: int, type_info: int, destructor: int) -> None:
        """Raise when the engine throws a C++ exception."""
        raise EngineError(-1, f"the engine threw an exception at {pointer:#x}")

    def _abort(self) -> None:
        """Raise when the engine calls abort."""
        raise EngineError(-1, "the engine aborted")

    def _resize_heap(self, requested: int) -> int:
        """Grow the heap to hold `requested` bytes. Return 1 on success.

        The engine treats a zero as "no more memory" and turns it into
        its own out of memory code, so a refusal here becomes a clean
        engine error and not a crash.
        """
        memory = self._memory
        if memory is None:
            return 0
        # Emscripten passes the size as a signed 32 bit value, so a very
        # large request arrives negative.
        if requested < 0 or requested > MAX_HEAP_BYTES:
            logger.warning("the engine asked for %s bytes, which is refused", requested)
            return 0
        current = memory.size(self._store) * _PAGE_BYTES
        if requested <= current:
            return 1
        pages = (requested - current + _PAGE_BYTES - 1) // _PAGE_BYTES
        try:
            memory.grow(self._store, pages)
        # wasmtime raises more than one type when a grow fails, and
        # the reason does not change what this must do.
        except Exception:
            logger.warning("the heap could not grow to %s bytes", requested)
            return 0
        return 1

    # --- memory --------------------------------------------------------

    @property
    def _mem(self) -> wasmtime.Memory:
        assert self._memory is not None
        return self._memory

    def _read(self, pointer: int, length: int) -> bytes:
        """Return bytes from the engine heap."""
        return bytes(self._mem.read(self._store, pointer, pointer + length))

    def _write(self, pointer: int, data: bytes) -> None:
        """Write bytes into the engine heap."""
        self._mem.write(self._store, data, pointer)

    @contextmanager
    def _scratch(self, length: int) -> Iterator[int]:
        """Give a block of engine memory back when the block is done.

        The module has no garbage collector. A run allocates many times,
        so every allocation must be freed even when a call raises.
        """
        pointer = int(self._functions["splat_malloc"](self._store, length))
        if not pointer:
            raise EngineError(-1, "splat_malloc")
        try:
            yield pointer
        finally:
            self._functions["splat_free"](self._store, pointer)

    def _call(self, name: str, *arguments: float | int) -> int:
        """Call the engine and raise on a negative return code."""
        result = int(self._functions[name](self._store, *arguments))
        if result < 0:
            raise EngineError(result, name)
        return result

    # --- the run -------------------------------------------------------

    @contextmanager
    def run(self, params: EngineParams) -> Iterator["EngineRun"]:
        """Set up one prediction and take it down again."""
        handle = self._call("splat_create", *params.to_arguments())
        run = EngineRun(self, handle, params.resolution_ippd)
        try:
            yield run
        finally:
            self._functions["splat_destroy"](self._store, handle)


class EngineRun:
    """One prediction in progress.

    Use `SplatInstance.run` to make one. The handle is closed when the
    block ends, so a run cannot outlive its memory.
    """

    def __init__(self, instance: SplatInstance, handle: int, resolution_ippd: int) -> None:
        self._instance = instance
        self._handle = handle
        self._ippd = resolution_ippd

    @property
    def _cells_per_page(self) -> int:
        return self._ippd * self._ippd

    def pages(self) -> list[PageRef]:
        """Return the elevation pages this run needs, in engine order.

        The index of a page in this list is the index `load_page` takes.
        """
        count = self._instance._call("splat_page_count", self._handle)
        refs: list[PageRef] = []
        with self._instance._scratch(8) as out:
            for index in range(count):
                self._instance._call("splat_page_info", self._handle, index, out)
                raw = self._instance._read(out, 8)
                north = int.from_bytes(raw[0:4], "little", signed=True)
                west = int.from_bytes(raw[4:8], "little", signed=True)
                refs.append(PageRef(north, west))
        return refs

    def load_page(self, index: int, page: bytes) -> None:
        """Give the engine one elevation page.

        The page is the little-endian int16 block that
        `sonoran/terrain` writes. A page the run never gets is read as
        sea level, and the coverage over it is drawn on flat ground.
        """
        expected = self._cells_per_page * 2
        if len(page) != expected:
            raise ValueError(f"page {index}: expected {expected} bytes, got {len(page)}")
        with self._instance._scratch(len(page)) as pointer:
            self._instance._write(pointer, page)
            self._instance._call("splat_load_page", self._handle, index, pointer)

    def radial_count(self) -> int:
        """Return how many radials this run sweeps."""
        return self._instance._call("splat_radial_count", self._handle)

    def run_radials(self, start: int, count: int) -> int:
        """Sweep a slice of the radials.

        The engine computes each point at the first radial that reaches
        it, so a slice may be run in any order.
        """
        return self._instance._call("splat_run_radials", self._handle, start, count)

    def run_all_radials(self, chunk: int = 64) -> None:
        """Sweep every radial, a chunk at a time."""
        total = self.radial_count()
        start = 0
        while start < total:
            self.run_radials(start, min(chunk, total - start))
            start += chunk

    def rasterize(self) -> None:
        """Turn the swept radials into the two rasters."""
        self._instance._call("splat_rasterize", self._handle)

    def region(self) -> Region:
        """Return the ground the rasters cover."""
        with self._instance._scratch(8 * 8) as out:
            self._instance._call("splat_region_info", self._handle, out)
            raw = self._instance._read(out, 64)
        numbers = struct.unpack("<8d", raw)
        return Region(
            width=int(numbers[0]),
            height=int(numbers[1]),
            north=numbers[2],
            south=numbers[3],
            east=numbers[4],
            west=numbers[5],
            radials=int(numbers[6]),
            pages=int(numbers[7]),
        )

    def errnum_counts(self) -> tuple[int, ...]:
        """Return how many times each ITM warning came up."""
        with self._instance._scratch(ERRNUM_COUNT * 4) as out:
            self._instance._call("splat_errnum_counts", self._handle, out)
            raw = self._instance._read(out, ERRNUM_COUNT * 4)
        return tuple(
            int.from_bytes(raw[i * 4 : i * 4 + 4], "little", signed=True)
            for i in range(ERRNUM_COUNT)
        )

    def raster(self) -> Raster:
        """Return the rasters. Call `rasterize` first."""
        region = self.region()
        cells = region.width * region.height

        signal_pointer = int(
            self._instance._functions["splat_signal_ptr"](self._instance._store, self._handle)
        )
        if not signal_pointer:
            raise EngineError(-2, "no signal raster: rasterize first")
        mask_pointer = int(
            self._instance._functions["splat_mask_ptr"](self._instance._store, self._handle)
        )
        if not mask_pointer:
            raise EngineError(-2, "no mask raster: rasterize first")

        return Raster(
            region=region,
            signal=self._instance._read(signal_pointer, cells),
            mask=self._instance._read(mask_pointer, cells),
            errnum_counts=self.errnum_counts(),
        )

    def point_to_point(self, latitude: float, longitude: float, height_m: float) -> Link:
        """Return one link from the transmitter to a place.

        `height_m` is the height of the receiving antenna above the
        ground there, in metres.
        """
        with self._instance._scratch(5 * 8) as out:
            points = self._instance._call(
                "splat_point_to_point",
                self._handle,
                latitude,
                longitude,
                metres_to_feet(height_m),
                out,
            )
            loss, dbm, distance, azimuth, errno = struct.unpack(
                "<5d", self._instance._read(out, 40)
            )
            profile: list[ProfilePoint] = []
            profile_pointer = int(
                self._instance._functions["splat_p2p_profile_ptr"](
                    self._instance._store, self._handle
                )
            )
            if profile_pointer and points:
                raw = self._instance._read(profile_pointer, points * 16)
                for index in range(points):
                    step, ground = struct.unpack("<2d", raw[index * 16 : index * 16 + 16])
                    profile.append(ProfilePoint(step, ground))

        return Link(
            loss_db=loss,
            dbm=dbm,
            distance_km=distance,
            azimuth_deg=azimuth,
            itm_errno=int(errno),
            profile=profile,
        )


def predict(
    instance: SplatInstance,
    params: EngineParams,
    pages: Sequence[bytes | None],
) -> Raster:
    """Run one whole prediction and return its rasters.

    `pages` must be in the order `EngineRun.pages` gives. A None entry
    is a page the terrain service does not hold. The engine reads a page
    it never got as sea level, so coverage over that ground is drawn on
    flat land. The caller must say so.
    """
    with instance.run(params) as run:
        for index, page in enumerate(pages):
            if page is not None:
                run.load_page(index, page)
        run.run_all_radials()
        run.rasterize()
        return run.raster()
