/*
 * Leaflet settings that every map on the dashboard shares.
 *
 * Loaded straight after leaflet.js and before any page script, so each
 * map is made with these already in place: the live map, the node page
 * map, coverage, gaps, the planner and RF. Setting them once here means
 * a new map cannot forget them.
 */
(function mapDefaults() {
  if (!window.L) return;

  const matches = (query) => Boolean(window.matchMedia && window.matchMedia(query).matches);

  /*
   * A finger-sized hit area for the dots on a touch screen (#266).
   *
   * Every map draws its nodes on Leaflet's canvas renderer
   * (`preferCanvas`), and a canvas renderer counts a tap as a hit only
   * inside the drawn circle: its `tolerance` is 0 unless it is set. A
   * dot is 2.5 to 6.5 px in radius, depending on the zoom, so the target
   * was 5 to 13 px across. Apple and Google ask for 44 to 48.
   *
   * 20 px of tolerance makes the smallest dot a 45 px target
   * (2 x (2.5 + 20)). The issue proposed 12 to 15 px, which leaves the
   * smallest dot at 29 to 35 px, short of the 44 px it asked for.
   * tar1090 uses 20 to 30 px on mobile for the same problem.
   *
   * `(pointer: coarse)`, not a width. An iPad in landscape is 1112 px
   * wide and has no mouse. A mouse keeps the exact target it had.
   */
  const TOUCH_TOLERANCE_PX = 20;

  if (matches('(pointer: coarse)')) {
    L.Canvas.mergeOptions({ tolerance: TOUCH_TOLERANCE_PX });
    /*
     * The tolerance is a canvas setting, and two maps did not ask for a
     * canvas: the node page's and the packet page's. On SVG a hit is the
     * drawn shape and nothing more, so the packet page's dots, which
     * open a bubble, stayed 14 to 16 px targets. On a touch screen every
     * map draws on a canvas. The dots look the same on either.
     */
    L.Map.mergeOptions({ preferCanvas: true });
    /*
     * The NEAREST dot wins a tap, not the one drawn last.
     *
     * With 20 px round every dot, the targets overlap wherever nodes are
     * close, and Phoenix at the opening zoom is hundreds of dots in a
     * few hundred pixels. Leaflet's own `_onClick` gives the tap to the
     * last layer drawn that contains the point, so a tap square on one
     * dot could open its neighbour, whose wider target reached over it.
     *
     * This is Leaflet 1.9.4's `_onClick` with one change: among the
     * circles that contain the point, the one whose edge is closest
     * wins, and a tie goes to the one drawn last, as before. A layer
     * that is not a circle (a link line) is chosen only when no circle
     * was hit, which is what Leaflet did for it anyway.
     */
    L.Canvas.include({
      _onClick(event) {
        const point = this._map.mouseEventToLayerPoint(event);
        const tapped = event.type === 'click' || event.type === 'preclick';
        let last = null;
        let nearest = null;
        let nearestGap = Infinity;
        for (let order = this._drawFirst; order; order = order.next) {
          const layer = order.layer;
          if (!layer.options.interactive || !layer._containsPoint(point)) continue;
          if (tapped && this._map._draggableMoved(layer)) continue;
          last = layer;
          if (layer._point && typeof layer._radius === 'number') {
            const gap = point.distanceTo(layer._point) - layer._radius;
            if (gap <= nearestGap) {
              nearest = layer;
              nearestGap = gap;
            }
          }
        }
        const chosen = nearest || last;
        this._fireEvent(chosen ? [chosen] : false, event);
      },
    });
  }

  // For the console and the e2e: what this browser was given.
  window.SonoranMapDefaults = {
    touchTolerance: matches('(pointer: coarse)') ? TOUCH_TOLERANCE_PX : 0,
  };
})();
