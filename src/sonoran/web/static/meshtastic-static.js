/*eslint-disable block-scoped-var, id-length, no-control-regex, no-magic-numbers, no-prototype-builtins, no-redeclare, no-shadow, no-var, sort-vars*/
import $protobuf from "./protobuf-runtime.js";

// Common aliases
const $Reader = $protobuf.Reader, $Writer = $protobuf.Writer, $util = $protobuf.util;

// Exported root namespace
const $root = $protobuf.roots["default"] || ($protobuf.roots["default"] = {});

export const meshtastic = $root.meshtastic = (() => {

    /**
     * Namespace meshtastic.
     * @exports meshtastic
     * @namespace
     */
    const meshtastic = {};

    meshtastic.Position = (function() {

        /**
         * Properties of a Position.
         * @memberof meshtastic
         * @interface IPosition
         * @property {number|null} [latitudeI] Position latitudeI
         * @property {number|null} [longitudeI] Position longitudeI
         * @property {number|null} [altitude] Position altitude
         * @property {number|null} [time] Position time
         */

        /**
         * Constructs a new Position.
         * @memberof meshtastic
         * @classdesc Represents a Position.
         * @implements IPosition
         * @constructor
         * @param {meshtastic.IPosition=} [properties] Properties to set
         */
        function Position(properties) {
            if (properties)
                for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                    if (properties[keys[i]] != null && keys[i] !== "__proto__")
                        this[keys[i]] = properties[keys[i]];
        }

        /**
         * Position latitudeI.
         * @member {number} latitudeI
         * @memberof meshtastic.Position
         * @instance
         */
        Position.prototype.latitudeI = 0;

        /**
         * Position longitudeI.
         * @member {number} longitudeI
         * @memberof meshtastic.Position
         * @instance
         */
        Position.prototype.longitudeI = 0;

        /**
         * Position altitude.
         * @member {number} altitude
         * @memberof meshtastic.Position
         * @instance
         */
        Position.prototype.altitude = 0;

        /**
         * Position time.
         * @member {number} time
         * @memberof meshtastic.Position
         * @instance
         */
        Position.prototype.time = 0;

        /**
         * Creates a new Position instance using the specified properties.
         * @function create
         * @memberof meshtastic.Position
         * @static
         * @param {meshtastic.IPosition=} [properties] Properties to set
         * @returns {meshtastic.Position} Position instance
         */
        Position.create = function create(properties) {
            return new Position(properties);
        };

        /**
         * Encodes the specified Position message. Does not implicitly {@link meshtastic.Position.verify|verify} messages.
         * @function encode
         * @memberof meshtastic.Position
         * @static
         * @param {meshtastic.IPosition} message Position message or plain object to encode
         * @param {$protobuf.Writer} [writer] Writer to encode to
         * @returns {$protobuf.Writer} Writer
         */
        Position.encode = function encode(message, writer, q) {
            if (!writer)
                writer = $Writer.create();
            if (q === undefined)
                q = 0;
            if (q > $util.recursionLimit)
                throw Error("max depth exceeded");
            if (message.latitudeI != null && Object.hasOwnProperty.call(message, "latitudeI"))
                writer.uint32(/* id 1, wireType 5 =*/13).sfixed32(message.latitudeI);
            if (message.longitudeI != null && Object.hasOwnProperty.call(message, "longitudeI"))
                writer.uint32(/* id 2, wireType 5 =*/21).sfixed32(message.longitudeI);
            if (message.altitude != null && Object.hasOwnProperty.call(message, "altitude"))
                writer.uint32(/* id 3, wireType 0 =*/24).int32(message.altitude);
            if (message.time != null && Object.hasOwnProperty.call(message, "time"))
                writer.uint32(/* id 4, wireType 5 =*/37).fixed32(message.time);
            return writer;
        };

        /**
         * Decodes a Position message from the specified reader or buffer.
         * @function decode
         * @memberof meshtastic.Position
         * @static
         * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
         * @param {number} [length] Message length if known beforehand
         * @returns {meshtastic.Position} Position
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        Position.decode = function decode(reader, length, error, long) {
            if (!(reader instanceof $Reader))
                reader = $Reader.create(reader);
            if (long === undefined)
                long = 0;
            if (long > $Reader.recursionLimit)
                throw Error("maximum nesting depth exceeded");
            let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.Position();
            while (reader.pos < end) {
                let tag = reader.uint32();
                if (tag === error)
                    break;
                switch (tag >>> 3) {
                case 1: {
                        message.latitudeI = reader.sfixed32();
                        break;
                    }
                case 2: {
                        message.longitudeI = reader.sfixed32();
                        break;
                    }
                case 3: {
                        message.altitude = reader.int32();
                        break;
                    }
                case 4: {
                        message.time = reader.fixed32();
                        break;
                    }
                default:
                    reader.skipType(tag & 7, long);
                    break;
                }
            }
            return message;
        };

        /**
         * Verifies a Position message.
         * @function verify
         * @memberof meshtastic.Position
         * @static
         * @param {Object.<string,*>} message Plain object to verify
         * @returns {string|null} `null` if valid, otherwise the reason why it is not
         */
        Position.verify = function verify(message, long) {
            if (typeof message !== "object" || message === null)
                return "object expected";
            if (long === undefined)
                long = 0;
            if (long > $util.recursionLimit)
                return "maximum nesting depth exceeded";
            if (message.latitudeI != null && Object.hasOwnProperty.call(message, "latitudeI"))
                if (!$util.isInteger(message.latitudeI))
                    return "latitudeI: integer expected";
            if (message.longitudeI != null && Object.hasOwnProperty.call(message, "longitudeI"))
                if (!$util.isInteger(message.longitudeI))
                    return "longitudeI: integer expected";
            if (message.altitude != null && Object.hasOwnProperty.call(message, "altitude"))
                if (!$util.isInteger(message.altitude))
                    return "altitude: integer expected";
            if (message.time != null && Object.hasOwnProperty.call(message, "time"))
                if (!$util.isInteger(message.time))
                    return "time: integer expected";
            return null;
        };

        /**
         * Gets the default type url for Position
         * @function getTypeUrl
         * @memberof meshtastic.Position
         * @static
         * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns {string} The default type url
         */
        Position.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
            if (typeUrlPrefix === undefined) {
                typeUrlPrefix = "type.googleapis.com";
            }
            return typeUrlPrefix + "/meshtastic.Position";
        };

        return Position;
    })();

    meshtastic.ModuleSettings = (function() {

        /**
         * Properties of a ModuleSettings.
         * @memberof meshtastic
         * @interface IModuleSettings
         * @property {number|null} [positionPrecision] ModuleSettings positionPrecision
         * @property {boolean|null} [isMuted] ModuleSettings isMuted
         */

        /**
         * Constructs a new ModuleSettings.
         * @memberof meshtastic
         * @classdesc Represents a ModuleSettings.
         * @implements IModuleSettings
         * @constructor
         * @param {meshtastic.IModuleSettings=} [properties] Properties to set
         */
        function ModuleSettings(properties) {
            if (properties)
                for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                    if (properties[keys[i]] != null && keys[i] !== "__proto__")
                        this[keys[i]] = properties[keys[i]];
        }

        /**
         * ModuleSettings positionPrecision.
         * @member {number} positionPrecision
         * @memberof meshtastic.ModuleSettings
         * @instance
         */
        ModuleSettings.prototype.positionPrecision = 0;

        /**
         * ModuleSettings isMuted.
         * @member {boolean} isMuted
         * @memberof meshtastic.ModuleSettings
         * @instance
         */
        ModuleSettings.prototype.isMuted = false;

        /**
         * Creates a new ModuleSettings instance using the specified properties.
         * @function create
         * @memberof meshtastic.ModuleSettings
         * @static
         * @param {meshtastic.IModuleSettings=} [properties] Properties to set
         * @returns {meshtastic.ModuleSettings} ModuleSettings instance
         */
        ModuleSettings.create = function create(properties) {
            return new ModuleSettings(properties);
        };

        /**
         * Encodes the specified ModuleSettings message. Does not implicitly {@link meshtastic.ModuleSettings.verify|verify} messages.
         * @function encode
         * @memberof meshtastic.ModuleSettings
         * @static
         * @param {meshtastic.IModuleSettings} message ModuleSettings message or plain object to encode
         * @param {$protobuf.Writer} [writer] Writer to encode to
         * @returns {$protobuf.Writer} Writer
         */
        ModuleSettings.encode = function encode(message, writer, q) {
            if (!writer)
                writer = $Writer.create();
            if (q === undefined)
                q = 0;
            if (q > $util.recursionLimit)
                throw Error("max depth exceeded");
            if (message.positionPrecision != null && Object.hasOwnProperty.call(message, "positionPrecision"))
                writer.uint32(/* id 1, wireType 0 =*/8).uint32(message.positionPrecision);
            if (message.isMuted != null && Object.hasOwnProperty.call(message, "isMuted"))
                writer.uint32(/* id 2, wireType 0 =*/16).bool(message.isMuted);
            return writer;
        };

        /**
         * Decodes a ModuleSettings message from the specified reader or buffer.
         * @function decode
         * @memberof meshtastic.ModuleSettings
         * @static
         * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
         * @param {number} [length] Message length if known beforehand
         * @returns {meshtastic.ModuleSettings} ModuleSettings
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        ModuleSettings.decode = function decode(reader, length, error, long) {
            if (!(reader instanceof $Reader))
                reader = $Reader.create(reader);
            if (long === undefined)
                long = 0;
            if (long > $Reader.recursionLimit)
                throw Error("maximum nesting depth exceeded");
            let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleSettings();
            while (reader.pos < end) {
                let tag = reader.uint32();
                if (tag === error)
                    break;
                switch (tag >>> 3) {
                case 1: {
                        message.positionPrecision = reader.uint32();
                        break;
                    }
                case 2: {
                        message.isMuted = reader.bool();
                        break;
                    }
                default:
                    reader.skipType(tag & 7, long);
                    break;
                }
            }
            return message;
        };

        /**
         * Verifies a ModuleSettings message.
         * @function verify
         * @memberof meshtastic.ModuleSettings
         * @static
         * @param {Object.<string,*>} message Plain object to verify
         * @returns {string|null} `null` if valid, otherwise the reason why it is not
         */
        ModuleSettings.verify = function verify(message, long) {
            if (typeof message !== "object" || message === null)
                return "object expected";
            if (long === undefined)
                long = 0;
            if (long > $util.recursionLimit)
                return "maximum nesting depth exceeded";
            if (message.positionPrecision != null && Object.hasOwnProperty.call(message, "positionPrecision"))
                if (!$util.isInteger(message.positionPrecision))
                    return "positionPrecision: integer expected";
            if (message.isMuted != null && Object.hasOwnProperty.call(message, "isMuted"))
                if (typeof message.isMuted !== "boolean")
                    return "isMuted: boolean expected";
            return null;
        };

        /**
         * Gets the default type url for ModuleSettings
         * @function getTypeUrl
         * @memberof meshtastic.ModuleSettings
         * @static
         * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns {string} The default type url
         */
        ModuleSettings.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
            if (typeUrlPrefix === undefined) {
                typeUrlPrefix = "type.googleapis.com";
            }
            return typeUrlPrefix + "/meshtastic.ModuleSettings";
        };

        return ModuleSettings;
    })();

    meshtastic.ChannelSettings = (function() {

        /**
         * Properties of a ChannelSettings.
         * @memberof meshtastic
         * @interface IChannelSettings
         * @property {number|null} [channelNum] ChannelSettings channelNum
         * @property {Uint8Array|null} [psk] ChannelSettings psk
         * @property {string|null} [name] ChannelSettings name
         * @property {number|null} [id] ChannelSettings id
         * @property {boolean|null} [uplinkEnabled] ChannelSettings uplinkEnabled
         * @property {boolean|null} [downlinkEnabled] ChannelSettings downlinkEnabled
         * @property {meshtastic.IModuleSettings|null} [moduleSettings] ChannelSettings moduleSettings
         */

        /**
         * Constructs a new ChannelSettings.
         * @memberof meshtastic
         * @classdesc Represents a ChannelSettings.
         * @implements IChannelSettings
         * @constructor
         * @param {meshtastic.IChannelSettings=} [properties] Properties to set
         */
        function ChannelSettings(properties) {
            if (properties)
                for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                    if (properties[keys[i]] != null && keys[i] !== "__proto__")
                        this[keys[i]] = properties[keys[i]];
        }

        /**
         * ChannelSettings channelNum.
         * @member {number} channelNum
         * @memberof meshtastic.ChannelSettings
         * @instance
         */
        ChannelSettings.prototype.channelNum = 0;

        /**
         * ChannelSettings psk.
         * @member {Uint8Array} psk
         * @memberof meshtastic.ChannelSettings
         * @instance
         */
        ChannelSettings.prototype.psk = $util.newBuffer([]);

        /**
         * ChannelSettings name.
         * @member {string} name
         * @memberof meshtastic.ChannelSettings
         * @instance
         */
        ChannelSettings.prototype.name = "";

        /**
         * ChannelSettings id.
         * @member {number} id
         * @memberof meshtastic.ChannelSettings
         * @instance
         */
        ChannelSettings.prototype.id = 0;

        /**
         * ChannelSettings uplinkEnabled.
         * @member {boolean} uplinkEnabled
         * @memberof meshtastic.ChannelSettings
         * @instance
         */
        ChannelSettings.prototype.uplinkEnabled = false;

        /**
         * ChannelSettings downlinkEnabled.
         * @member {boolean} downlinkEnabled
         * @memberof meshtastic.ChannelSettings
         * @instance
         */
        ChannelSettings.prototype.downlinkEnabled = false;

        /**
         * ChannelSettings moduleSettings.
         * @member {meshtastic.IModuleSettings|null|undefined} moduleSettings
         * @memberof meshtastic.ChannelSettings
         * @instance
         */
        ChannelSettings.prototype.moduleSettings = null;

        /**
         * Creates a new ChannelSettings instance using the specified properties.
         * @function create
         * @memberof meshtastic.ChannelSettings
         * @static
         * @param {meshtastic.IChannelSettings=} [properties] Properties to set
         * @returns {meshtastic.ChannelSettings} ChannelSettings instance
         */
        ChannelSettings.create = function create(properties) {
            return new ChannelSettings(properties);
        };

        /**
         * Encodes the specified ChannelSettings message. Does not implicitly {@link meshtastic.ChannelSettings.verify|verify} messages.
         * @function encode
         * @memberof meshtastic.ChannelSettings
         * @static
         * @param {meshtastic.IChannelSettings} message ChannelSettings message or plain object to encode
         * @param {$protobuf.Writer} [writer] Writer to encode to
         * @returns {$protobuf.Writer} Writer
         */
        ChannelSettings.encode = function encode(message, writer, q) {
            if (!writer)
                writer = $Writer.create();
            if (q === undefined)
                q = 0;
            if (q > $util.recursionLimit)
                throw Error("max depth exceeded");
            if (message.channelNum != null && Object.hasOwnProperty.call(message, "channelNum"))
                writer.uint32(/* id 1, wireType 0 =*/8).uint32(message.channelNum);
            if (message.psk != null && Object.hasOwnProperty.call(message, "psk"))
                writer.uint32(/* id 2, wireType 2 =*/18).bytes(message.psk);
            if (message.name != null && Object.hasOwnProperty.call(message, "name"))
                writer.uint32(/* id 3, wireType 2 =*/26).string(message.name);
            if (message.id != null && Object.hasOwnProperty.call(message, "id"))
                writer.uint32(/* id 4, wireType 5 =*/37).fixed32(message.id);
            if (message.uplinkEnabled != null && Object.hasOwnProperty.call(message, "uplinkEnabled"))
                writer.uint32(/* id 5, wireType 0 =*/40).bool(message.uplinkEnabled);
            if (message.downlinkEnabled != null && Object.hasOwnProperty.call(message, "downlinkEnabled"))
                writer.uint32(/* id 6, wireType 0 =*/48).bool(message.downlinkEnabled);
            if (message.moduleSettings != null && Object.hasOwnProperty.call(message, "moduleSettings"))
                $root.meshtastic.ModuleSettings.encode(message.moduleSettings, writer.uint32(/* id 7, wireType 2 =*/58).fork(), q + 1).ldelim();
            return writer;
        };

        /**
         * Decodes a ChannelSettings message from the specified reader or buffer.
         * @function decode
         * @memberof meshtastic.ChannelSettings
         * @static
         * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
         * @param {number} [length] Message length if known beforehand
         * @returns {meshtastic.ChannelSettings} ChannelSettings
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        ChannelSettings.decode = function decode(reader, length, error, long) {
            if (!(reader instanceof $Reader))
                reader = $Reader.create(reader);
            if (long === undefined)
                long = 0;
            if (long > $Reader.recursionLimit)
                throw Error("maximum nesting depth exceeded");
            let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ChannelSettings();
            while (reader.pos < end) {
                let tag = reader.uint32();
                if (tag === error)
                    break;
                switch (tag >>> 3) {
                case 1: {
                        message.channelNum = reader.uint32();
                        break;
                    }
                case 2: {
                        message.psk = reader.bytes();
                        break;
                    }
                case 3: {
                        message.name = reader.string();
                        break;
                    }
                case 4: {
                        message.id = reader.fixed32();
                        break;
                    }
                case 5: {
                        message.uplinkEnabled = reader.bool();
                        break;
                    }
                case 6: {
                        message.downlinkEnabled = reader.bool();
                        break;
                    }
                case 7: {
                        message.moduleSettings = $root.meshtastic.ModuleSettings.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                default:
                    reader.skipType(tag & 7, long);
                    break;
                }
            }
            return message;
        };

        /**
         * Verifies a ChannelSettings message.
         * @function verify
         * @memberof meshtastic.ChannelSettings
         * @static
         * @param {Object.<string,*>} message Plain object to verify
         * @returns {string|null} `null` if valid, otherwise the reason why it is not
         */
        ChannelSettings.verify = function verify(message, long) {
            if (typeof message !== "object" || message === null)
                return "object expected";
            if (long === undefined)
                long = 0;
            if (long > $util.recursionLimit)
                return "maximum nesting depth exceeded";
            if (message.channelNum != null && Object.hasOwnProperty.call(message, "channelNum"))
                if (!$util.isInteger(message.channelNum))
                    return "channelNum: integer expected";
            if (message.psk != null && Object.hasOwnProperty.call(message, "psk"))
                if (!(message.psk && typeof message.psk.length === "number" || $util.isString(message.psk)))
                    return "psk: buffer expected";
            if (message.name != null && Object.hasOwnProperty.call(message, "name"))
                if (!$util.isString(message.name))
                    return "name: string expected";
            if (message.id != null && Object.hasOwnProperty.call(message, "id"))
                if (!$util.isInteger(message.id))
                    return "id: integer expected";
            if (message.uplinkEnabled != null && Object.hasOwnProperty.call(message, "uplinkEnabled"))
                if (typeof message.uplinkEnabled !== "boolean")
                    return "uplinkEnabled: boolean expected";
            if (message.downlinkEnabled != null && Object.hasOwnProperty.call(message, "downlinkEnabled"))
                if (typeof message.downlinkEnabled !== "boolean")
                    return "downlinkEnabled: boolean expected";
            if (message.moduleSettings != null && Object.hasOwnProperty.call(message, "moduleSettings")) {
                let error = $root.meshtastic.ModuleSettings.verify(message.moduleSettings, long + 1);
                if (error)
                    return "moduleSettings." + error;
            }
            return null;
        };

        /**
         * Gets the default type url for ChannelSettings
         * @function getTypeUrl
         * @memberof meshtastic.ChannelSettings
         * @static
         * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns {string} The default type url
         */
        ChannelSettings.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
            if (typeUrlPrefix === undefined) {
                typeUrlPrefix = "type.googleapis.com";
            }
            return typeUrlPrefix + "/meshtastic.ChannelSettings";
        };

        return ChannelSettings;
    })();

    meshtastic.Channel = (function() {

        /**
         * Properties of a Channel.
         * @memberof meshtastic
         * @interface IChannel
         * @property {number|null} [index] Channel index
         * @property {meshtastic.IChannelSettings|null} [settings] Channel settings
         * @property {meshtastic.Channel.Role|null} [role] Channel role
         */

        /**
         * Constructs a new Channel.
         * @memberof meshtastic
         * @classdesc Represents a Channel.
         * @implements IChannel
         * @constructor
         * @param {meshtastic.IChannel=} [properties] Properties to set
         */
        function Channel(properties) {
            if (properties)
                for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                    if (properties[keys[i]] != null && keys[i] !== "__proto__")
                        this[keys[i]] = properties[keys[i]];
        }

        /**
         * Channel index.
         * @member {number} index
         * @memberof meshtastic.Channel
         * @instance
         */
        Channel.prototype.index = 0;

        /**
         * Channel settings.
         * @member {meshtastic.IChannelSettings|null|undefined} settings
         * @memberof meshtastic.Channel
         * @instance
         */
        Channel.prototype.settings = null;

        /**
         * Channel role.
         * @member {meshtastic.Channel.Role} role
         * @memberof meshtastic.Channel
         * @instance
         */
        Channel.prototype.role = 0;

        /**
         * Creates a new Channel instance using the specified properties.
         * @function create
         * @memberof meshtastic.Channel
         * @static
         * @param {meshtastic.IChannel=} [properties] Properties to set
         * @returns {meshtastic.Channel} Channel instance
         */
        Channel.create = function create(properties) {
            return new Channel(properties);
        };

        /**
         * Encodes the specified Channel message. Does not implicitly {@link meshtastic.Channel.verify|verify} messages.
         * @function encode
         * @memberof meshtastic.Channel
         * @static
         * @param {meshtastic.IChannel} message Channel message or plain object to encode
         * @param {$protobuf.Writer} [writer] Writer to encode to
         * @returns {$protobuf.Writer} Writer
         */
        Channel.encode = function encode(message, writer, q) {
            if (!writer)
                writer = $Writer.create();
            if (q === undefined)
                q = 0;
            if (q > $util.recursionLimit)
                throw Error("max depth exceeded");
            if (message.index != null && Object.hasOwnProperty.call(message, "index"))
                writer.uint32(/* id 1, wireType 0 =*/8).int32(message.index);
            if (message.settings != null && Object.hasOwnProperty.call(message, "settings"))
                $root.meshtastic.ChannelSettings.encode(message.settings, writer.uint32(/* id 2, wireType 2 =*/18).fork(), q + 1).ldelim();
            if (message.role != null && Object.hasOwnProperty.call(message, "role"))
                writer.uint32(/* id 3, wireType 0 =*/24).int32(message.role);
            return writer;
        };

        /**
         * Decodes a Channel message from the specified reader or buffer.
         * @function decode
         * @memberof meshtastic.Channel
         * @static
         * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
         * @param {number} [length] Message length if known beforehand
         * @returns {meshtastic.Channel} Channel
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        Channel.decode = function decode(reader, length, error, long) {
            if (!(reader instanceof $Reader))
                reader = $Reader.create(reader);
            if (long === undefined)
                long = 0;
            if (long > $Reader.recursionLimit)
                throw Error("maximum nesting depth exceeded");
            let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.Channel();
            while (reader.pos < end) {
                let tag = reader.uint32();
                if (tag === error)
                    break;
                switch (tag >>> 3) {
                case 1: {
                        message.index = reader.int32();
                        break;
                    }
                case 2: {
                        message.settings = $root.meshtastic.ChannelSettings.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 3: {
                        message.role = reader.int32();
                        break;
                    }
                default:
                    reader.skipType(tag & 7, long);
                    break;
                }
            }
            return message;
        };

        /**
         * Verifies a Channel message.
         * @function verify
         * @memberof meshtastic.Channel
         * @static
         * @param {Object.<string,*>} message Plain object to verify
         * @returns {string|null} `null` if valid, otherwise the reason why it is not
         */
        Channel.verify = function verify(message, long) {
            if (typeof message !== "object" || message === null)
                return "object expected";
            if (long === undefined)
                long = 0;
            if (long > $util.recursionLimit)
                return "maximum nesting depth exceeded";
            if (message.index != null && Object.hasOwnProperty.call(message, "index"))
                if (!$util.isInteger(message.index))
                    return "index: integer expected";
            if (message.settings != null && Object.hasOwnProperty.call(message, "settings")) {
                let error = $root.meshtastic.ChannelSettings.verify(message.settings, long + 1);
                if (error)
                    return "settings." + error;
            }
            if (message.role != null && Object.hasOwnProperty.call(message, "role"))
                switch (message.role) {
                default:
                    return "role: enum value expected";
                case 0:
                case 1:
                case 2:
                    break;
                }
            return null;
        };

        /**
         * Gets the default type url for Channel
         * @function getTypeUrl
         * @memberof meshtastic.Channel
         * @static
         * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns {string} The default type url
         */
        Channel.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
            if (typeUrlPrefix === undefined) {
                typeUrlPrefix = "type.googleapis.com";
            }
            return typeUrlPrefix + "/meshtastic.Channel";
        };

        /**
         * Role enum.
         * @name meshtastic.Channel.Role
         * @enum {number}
         * @property {number} DISABLED=0 DISABLED value
         * @property {number} PRIMARY=1 PRIMARY value
         * @property {number} SECONDARY=2 SECONDARY value
         */
        Channel.Role = (function() {
            const valuesById = {}, values = Object.create(valuesById);
            values[valuesById[0] = "DISABLED"] = 0;
            values[valuesById[1] = "PRIMARY"] = 1;
            values[valuesById[2] = "SECONDARY"] = 2;
            return values;
        })();

        return Channel;
    })();

    meshtastic.ChannelSet = (function() {

        /**
         * Properties of a ChannelSet.
         * @memberof meshtastic
         * @interface IChannelSet
         * @property {Array.<meshtastic.IChannelSettings>|null} [settings] ChannelSet settings
         * @property {meshtastic.Config.ILoRaConfig|null} [loraConfig] ChannelSet loraConfig
         */

        /**
         * Constructs a new ChannelSet.
         * @memberof meshtastic
         * @classdesc Represents a ChannelSet.
         * @implements IChannelSet
         * @constructor
         * @param {meshtastic.IChannelSet=} [properties] Properties to set
         */
        function ChannelSet(properties) {
            this.settings = [];
            if (properties)
                for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                    if (properties[keys[i]] != null && keys[i] !== "__proto__")
                        this[keys[i]] = properties[keys[i]];
        }

        /**
         * ChannelSet settings.
         * @member {Array.<meshtastic.IChannelSettings>} settings
         * @memberof meshtastic.ChannelSet
         * @instance
         */
        ChannelSet.prototype.settings = $util.emptyArray;

        /**
         * ChannelSet loraConfig.
         * @member {meshtastic.Config.ILoRaConfig|null|undefined} loraConfig
         * @memberof meshtastic.ChannelSet
         * @instance
         */
        ChannelSet.prototype.loraConfig = null;

        /**
         * Creates a new ChannelSet instance using the specified properties.
         * @function create
         * @memberof meshtastic.ChannelSet
         * @static
         * @param {meshtastic.IChannelSet=} [properties] Properties to set
         * @returns {meshtastic.ChannelSet} ChannelSet instance
         */
        ChannelSet.create = function create(properties) {
            return new ChannelSet(properties);
        };

        /**
         * Encodes the specified ChannelSet message. Does not implicitly {@link meshtastic.ChannelSet.verify|verify} messages.
         * @function encode
         * @memberof meshtastic.ChannelSet
         * @static
         * @param {meshtastic.IChannelSet} message ChannelSet message or plain object to encode
         * @param {$protobuf.Writer} [writer] Writer to encode to
         * @returns {$protobuf.Writer} Writer
         */
        ChannelSet.encode = function encode(message, writer, q) {
            if (!writer)
                writer = $Writer.create();
            if (q === undefined)
                q = 0;
            if (q > $util.recursionLimit)
                throw Error("max depth exceeded");
            if (message.settings != null && message.settings.length)
                for (let i = 0; i < message.settings.length; ++i)
                    $root.meshtastic.ChannelSettings.encode(message.settings[i], writer.uint32(/* id 1, wireType 2 =*/10).fork(), q + 1).ldelim();
            if (message.loraConfig != null && Object.hasOwnProperty.call(message, "loraConfig"))
                $root.meshtastic.Config.LoRaConfig.encode(message.loraConfig, writer.uint32(/* id 2, wireType 2 =*/18).fork(), q + 1).ldelim();
            return writer;
        };

        /**
         * Decodes a ChannelSet message from the specified reader or buffer.
         * @function decode
         * @memberof meshtastic.ChannelSet
         * @static
         * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
         * @param {number} [length] Message length if known beforehand
         * @returns {meshtastic.ChannelSet} ChannelSet
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        ChannelSet.decode = function decode(reader, length, error, long) {
            if (!(reader instanceof $Reader))
                reader = $Reader.create(reader);
            if (long === undefined)
                long = 0;
            if (long > $Reader.recursionLimit)
                throw Error("maximum nesting depth exceeded");
            let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ChannelSet();
            while (reader.pos < end) {
                let tag = reader.uint32();
                if (tag === error)
                    break;
                switch (tag >>> 3) {
                case 1: {
                        if (!(message.settings && message.settings.length))
                            message.settings = [];
                        message.settings.push($root.meshtastic.ChannelSettings.decode(reader, reader.uint32(), undefined, long + 1));
                        break;
                    }
                case 2: {
                        message.loraConfig = $root.meshtastic.Config.LoRaConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                default:
                    reader.skipType(tag & 7, long);
                    break;
                }
            }
            return message;
        };

        /**
         * Verifies a ChannelSet message.
         * @function verify
         * @memberof meshtastic.ChannelSet
         * @static
         * @param {Object.<string,*>} message Plain object to verify
         * @returns {string|null} `null` if valid, otherwise the reason why it is not
         */
        ChannelSet.verify = function verify(message, long) {
            if (typeof message !== "object" || message === null)
                return "object expected";
            if (long === undefined)
                long = 0;
            if (long > $util.recursionLimit)
                return "maximum nesting depth exceeded";
            if (message.settings != null && Object.hasOwnProperty.call(message, "settings")) {
                if (!Array.isArray(message.settings))
                    return "settings: array expected";
                for (let i = 0; i < message.settings.length; ++i) {
                    let error = $root.meshtastic.ChannelSettings.verify(message.settings[i], long + 1);
                    if (error)
                        return "settings." + error;
                }
            }
            if (message.loraConfig != null && Object.hasOwnProperty.call(message, "loraConfig")) {
                let error = $root.meshtastic.Config.LoRaConfig.verify(message.loraConfig, long + 1);
                if (error)
                    return "loraConfig." + error;
            }
            return null;
        };

        /**
         * Gets the default type url for ChannelSet
         * @function getTypeUrl
         * @memberof meshtastic.ChannelSet
         * @static
         * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns {string} The default type url
         */
        ChannelSet.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
            if (typeUrlPrefix === undefined) {
                typeUrlPrefix = "type.googleapis.com";
            }
            return typeUrlPrefix + "/meshtastic.ChannelSet";
        };

        return ChannelSet;
    })();

    meshtastic.Config = (function() {

        /**
         * Namespace Config.
         * @memberof meshtastic
         * @namespace
         */
        const Config = {};

        Config.DeviceConfig = (function() {

            /**
             * Properties of a DeviceConfig.
             * @memberof meshtastic.Config
             * @interface IDeviceConfig
             * @property {meshtastic.Config.DeviceConfig.Role|null} [role] DeviceConfig role
             * @property {boolean|null} [serialEnabled] DeviceConfig serialEnabled
             * @property {number|null} [buttonGpio] DeviceConfig buttonGpio
             * @property {number|null} [buzzerGpio] DeviceConfig buzzerGpio
             * @property {number|null} [rebroadcastMode] DeviceConfig rebroadcastMode
             * @property {number|null} [nodeInfoBroadcastSecs] DeviceConfig nodeInfoBroadcastSecs
             * @property {boolean|null} [doubleTapAsButtonPress] DeviceConfig doubleTapAsButtonPress
             * @property {boolean|null} [isManaged] DeviceConfig isManaged
             * @property {boolean|null} [disableTripleClick] DeviceConfig disableTripleClick
             * @property {string|null} [tzdef] DeviceConfig tzdef
             * @property {boolean|null} [ledHeartbeatDisabled] DeviceConfig ledHeartbeatDisabled
             * @property {number|null} [buzzerMode] DeviceConfig buzzerMode
             */

            /**
             * Constructs a new DeviceConfig.
             * @memberof meshtastic.Config
             * @classdesc Represents a DeviceConfig.
             * @implements IDeviceConfig
             * @constructor
             * @param {meshtastic.Config.IDeviceConfig=} [properties] Properties to set
             */
            function DeviceConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * DeviceConfig role.
             * @member {meshtastic.Config.DeviceConfig.Role} role
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.role = 0;

            /**
             * DeviceConfig serialEnabled.
             * @member {boolean} serialEnabled
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.serialEnabled = false;

            /**
             * DeviceConfig buttonGpio.
             * @member {number} buttonGpio
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.buttonGpio = 0;

            /**
             * DeviceConfig buzzerGpio.
             * @member {number} buzzerGpio
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.buzzerGpio = 0;

            /**
             * DeviceConfig rebroadcastMode.
             * @member {number} rebroadcastMode
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.rebroadcastMode = 0;

            /**
             * DeviceConfig nodeInfoBroadcastSecs.
             * @member {number} nodeInfoBroadcastSecs
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.nodeInfoBroadcastSecs = 0;

            /**
             * DeviceConfig doubleTapAsButtonPress.
             * @member {boolean} doubleTapAsButtonPress
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.doubleTapAsButtonPress = false;

            /**
             * DeviceConfig isManaged.
             * @member {boolean} isManaged
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.isManaged = false;

            /**
             * DeviceConfig disableTripleClick.
             * @member {boolean} disableTripleClick
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.disableTripleClick = false;

            /**
             * DeviceConfig tzdef.
             * @member {string} tzdef
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.tzdef = "";

            /**
             * DeviceConfig ledHeartbeatDisabled.
             * @member {boolean} ledHeartbeatDisabled
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.ledHeartbeatDisabled = false;

            /**
             * DeviceConfig buzzerMode.
             * @member {number} buzzerMode
             * @memberof meshtastic.Config.DeviceConfig
             * @instance
             */
            DeviceConfig.prototype.buzzerMode = 0;

            /**
             * Creates a new DeviceConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.Config.DeviceConfig
             * @static
             * @param {meshtastic.Config.IDeviceConfig=} [properties] Properties to set
             * @returns {meshtastic.Config.DeviceConfig} DeviceConfig instance
             */
            DeviceConfig.create = function create(properties) {
                return new DeviceConfig(properties);
            };

            /**
             * Encodes the specified DeviceConfig message. Does not implicitly {@link meshtastic.Config.DeviceConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.Config.DeviceConfig
             * @static
             * @param {meshtastic.Config.IDeviceConfig} message DeviceConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            DeviceConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.role != null && Object.hasOwnProperty.call(message, "role"))
                    writer.uint32(/* id 1, wireType 0 =*/8).int32(message.role);
                if (message.serialEnabled != null && Object.hasOwnProperty.call(message, "serialEnabled"))
                    writer.uint32(/* id 2, wireType 0 =*/16).bool(message.serialEnabled);
                if (message.buttonGpio != null && Object.hasOwnProperty.call(message, "buttonGpio"))
                    writer.uint32(/* id 4, wireType 0 =*/32).uint32(message.buttonGpio);
                if (message.buzzerGpio != null && Object.hasOwnProperty.call(message, "buzzerGpio"))
                    writer.uint32(/* id 5, wireType 0 =*/40).uint32(message.buzzerGpio);
                if (message.rebroadcastMode != null && Object.hasOwnProperty.call(message, "rebroadcastMode"))
                    writer.uint32(/* id 6, wireType 0 =*/48).uint32(message.rebroadcastMode);
                if (message.nodeInfoBroadcastSecs != null && Object.hasOwnProperty.call(message, "nodeInfoBroadcastSecs"))
                    writer.uint32(/* id 7, wireType 0 =*/56).uint32(message.nodeInfoBroadcastSecs);
                if (message.doubleTapAsButtonPress != null && Object.hasOwnProperty.call(message, "doubleTapAsButtonPress"))
                    writer.uint32(/* id 8, wireType 0 =*/64).bool(message.doubleTapAsButtonPress);
                if (message.isManaged != null && Object.hasOwnProperty.call(message, "isManaged"))
                    writer.uint32(/* id 9, wireType 0 =*/72).bool(message.isManaged);
                if (message.disableTripleClick != null && Object.hasOwnProperty.call(message, "disableTripleClick"))
                    writer.uint32(/* id 10, wireType 0 =*/80).bool(message.disableTripleClick);
                if (message.tzdef != null && Object.hasOwnProperty.call(message, "tzdef"))
                    writer.uint32(/* id 11, wireType 2 =*/90).string(message.tzdef);
                if (message.ledHeartbeatDisabled != null && Object.hasOwnProperty.call(message, "ledHeartbeatDisabled"))
                    writer.uint32(/* id 12, wireType 0 =*/96).bool(message.ledHeartbeatDisabled);
                if (message.buzzerMode != null && Object.hasOwnProperty.call(message, "buzzerMode"))
                    writer.uint32(/* id 13, wireType 0 =*/104).uint32(message.buzzerMode);
                return writer;
            };

            /**
             * Decodes a DeviceConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.Config.DeviceConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.Config.DeviceConfig} DeviceConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            DeviceConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.Config.DeviceConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.role = reader.int32();
                            break;
                        }
                    case 2: {
                            message.serialEnabled = reader.bool();
                            break;
                        }
                    case 4: {
                            message.buttonGpio = reader.uint32();
                            break;
                        }
                    case 5: {
                            message.buzzerGpio = reader.uint32();
                            break;
                        }
                    case 6: {
                            message.rebroadcastMode = reader.uint32();
                            break;
                        }
                    case 7: {
                            message.nodeInfoBroadcastSecs = reader.uint32();
                            break;
                        }
                    case 8: {
                            message.doubleTapAsButtonPress = reader.bool();
                            break;
                        }
                    case 9: {
                            message.isManaged = reader.bool();
                            break;
                        }
                    case 10: {
                            message.disableTripleClick = reader.bool();
                            break;
                        }
                    case 11: {
                            message.tzdef = reader.string();
                            break;
                        }
                    case 12: {
                            message.ledHeartbeatDisabled = reader.bool();
                            break;
                        }
                    case 13: {
                            message.buzzerMode = reader.uint32();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a DeviceConfig message.
             * @function verify
             * @memberof meshtastic.Config.DeviceConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            DeviceConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.role != null && Object.hasOwnProperty.call(message, "role"))
                    switch (message.role) {
                    default:
                        return "role: enum value expected";
                    case 0:
                    case 1:
                    case 2:
                    case 3:
                    case 4:
                    case 5:
                    case 6:
                    case 7:
                    case 8:
                    case 9:
                    case 10:
                    case 11:
                    case 12:
                        break;
                    }
                if (message.serialEnabled != null && Object.hasOwnProperty.call(message, "serialEnabled"))
                    if (typeof message.serialEnabled !== "boolean")
                        return "serialEnabled: boolean expected";
                if (message.buttonGpio != null && Object.hasOwnProperty.call(message, "buttonGpio"))
                    if (!$util.isInteger(message.buttonGpio))
                        return "buttonGpio: integer expected";
                if (message.buzzerGpio != null && Object.hasOwnProperty.call(message, "buzzerGpio"))
                    if (!$util.isInteger(message.buzzerGpio))
                        return "buzzerGpio: integer expected";
                if (message.rebroadcastMode != null && Object.hasOwnProperty.call(message, "rebroadcastMode"))
                    if (!$util.isInteger(message.rebroadcastMode))
                        return "rebroadcastMode: integer expected";
                if (message.nodeInfoBroadcastSecs != null && Object.hasOwnProperty.call(message, "nodeInfoBroadcastSecs"))
                    if (!$util.isInteger(message.nodeInfoBroadcastSecs))
                        return "nodeInfoBroadcastSecs: integer expected";
                if (message.doubleTapAsButtonPress != null && Object.hasOwnProperty.call(message, "doubleTapAsButtonPress"))
                    if (typeof message.doubleTapAsButtonPress !== "boolean")
                        return "doubleTapAsButtonPress: boolean expected";
                if (message.isManaged != null && Object.hasOwnProperty.call(message, "isManaged"))
                    if (typeof message.isManaged !== "boolean")
                        return "isManaged: boolean expected";
                if (message.disableTripleClick != null && Object.hasOwnProperty.call(message, "disableTripleClick"))
                    if (typeof message.disableTripleClick !== "boolean")
                        return "disableTripleClick: boolean expected";
                if (message.tzdef != null && Object.hasOwnProperty.call(message, "tzdef"))
                    if (!$util.isString(message.tzdef))
                        return "tzdef: string expected";
                if (message.ledHeartbeatDisabled != null && Object.hasOwnProperty.call(message, "ledHeartbeatDisabled"))
                    if (typeof message.ledHeartbeatDisabled !== "boolean")
                        return "ledHeartbeatDisabled: boolean expected";
                if (message.buzzerMode != null && Object.hasOwnProperty.call(message, "buzzerMode"))
                    if (!$util.isInteger(message.buzzerMode))
                        return "buzzerMode: integer expected";
                return null;
            };

            /**
             * Gets the default type url for DeviceConfig
             * @function getTypeUrl
             * @memberof meshtastic.Config.DeviceConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            DeviceConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.Config.DeviceConfig";
            };

            /**
             * Role enum.
             * @name meshtastic.Config.DeviceConfig.Role
             * @enum {number}
             * @property {number} CLIENT=0 CLIENT value
             * @property {number} CLIENT_MUTE=1 CLIENT_MUTE value
             * @property {number} ROUTER=2 ROUTER value
             * @property {number} ROUTER_CLIENT=3 ROUTER_CLIENT value
             * @property {number} REPEATER=4 REPEATER value
             * @property {number} TRACKER=5 TRACKER value
             * @property {number} SENSOR=6 SENSOR value
             * @property {number} TAK=7 TAK value
             * @property {number} CLIENT_HIDDEN=8 CLIENT_HIDDEN value
             * @property {number} LOST_AND_FOUND=9 LOST_AND_FOUND value
             * @property {number} TAK_TRACKER=10 TAK_TRACKER value
             * @property {number} ROUTER_LATE=11 ROUTER_LATE value
             * @property {number} CLIENT_BASE=12 CLIENT_BASE value
             */
            DeviceConfig.Role = (function() {
                const valuesById = {}, values = Object.create(valuesById);
                values[valuesById[0] = "CLIENT"] = 0;
                values[valuesById[1] = "CLIENT_MUTE"] = 1;
                values[valuesById[2] = "ROUTER"] = 2;
                values[valuesById[3] = "ROUTER_CLIENT"] = 3;
                values[valuesById[4] = "REPEATER"] = 4;
                values[valuesById[5] = "TRACKER"] = 5;
                values[valuesById[6] = "SENSOR"] = 6;
                values[valuesById[7] = "TAK"] = 7;
                values[valuesById[8] = "CLIENT_HIDDEN"] = 8;
                values[valuesById[9] = "LOST_AND_FOUND"] = 9;
                values[valuesById[10] = "TAK_TRACKER"] = 10;
                values[valuesById[11] = "ROUTER_LATE"] = 11;
                values[valuesById[12] = "CLIENT_BASE"] = 12;
                return values;
            })();

            return DeviceConfig;
        })();

        Config.PositionConfig = (function() {

            /**
             * Properties of a PositionConfig.
             * @memberof meshtastic.Config
             * @interface IPositionConfig
             * @property {number|null} [positionBroadcastSecs] PositionConfig positionBroadcastSecs
             * @property {boolean|null} [positionBroadcastSmartEnabled] PositionConfig positionBroadcastSmartEnabled
             * @property {boolean|null} [fixedPosition] PositionConfig fixedPosition
             * @property {boolean|null} [gpsEnabled] PositionConfig gpsEnabled
             * @property {number|null} [gpsUpdateInterval] PositionConfig gpsUpdateInterval
             * @property {number|null} [gpsAttemptTime] PositionConfig gpsAttemptTime
             * @property {number|null} [positionFlags] PositionConfig positionFlags
             * @property {number|null} [rxGpio] PositionConfig rxGpio
             * @property {number|null} [txGpio] PositionConfig txGpio
             * @property {number|null} [broadcastSmartMinimumDistance] PositionConfig broadcastSmartMinimumDistance
             * @property {number|null} [broadcastSmartMinimumIntervalSecs] PositionConfig broadcastSmartMinimumIntervalSecs
             * @property {number|null} [gpsEnGpio] PositionConfig gpsEnGpio
             * @property {number|null} [gpsMode] PositionConfig gpsMode
             */

            /**
             * Constructs a new PositionConfig.
             * @memberof meshtastic.Config
             * @classdesc Represents a PositionConfig.
             * @implements IPositionConfig
             * @constructor
             * @param {meshtastic.Config.IPositionConfig=} [properties] Properties to set
             */
            function PositionConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * PositionConfig positionBroadcastSecs.
             * @member {number} positionBroadcastSecs
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.positionBroadcastSecs = 0;

            /**
             * PositionConfig positionBroadcastSmartEnabled.
             * @member {boolean} positionBroadcastSmartEnabled
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.positionBroadcastSmartEnabled = false;

            /**
             * PositionConfig fixedPosition.
             * @member {boolean} fixedPosition
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.fixedPosition = false;

            /**
             * PositionConfig gpsEnabled.
             * @member {boolean} gpsEnabled
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.gpsEnabled = false;

            /**
             * PositionConfig gpsUpdateInterval.
             * @member {number} gpsUpdateInterval
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.gpsUpdateInterval = 0;

            /**
             * PositionConfig gpsAttemptTime.
             * @member {number} gpsAttemptTime
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.gpsAttemptTime = 0;

            /**
             * PositionConfig positionFlags.
             * @member {number} positionFlags
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.positionFlags = 0;

            /**
             * PositionConfig rxGpio.
             * @member {number} rxGpio
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.rxGpio = 0;

            /**
             * PositionConfig txGpio.
             * @member {number} txGpio
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.txGpio = 0;

            /**
             * PositionConfig broadcastSmartMinimumDistance.
             * @member {number} broadcastSmartMinimumDistance
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.broadcastSmartMinimumDistance = 0;

            /**
             * PositionConfig broadcastSmartMinimumIntervalSecs.
             * @member {number} broadcastSmartMinimumIntervalSecs
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.broadcastSmartMinimumIntervalSecs = 0;

            /**
             * PositionConfig gpsEnGpio.
             * @member {number} gpsEnGpio
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.gpsEnGpio = 0;

            /**
             * PositionConfig gpsMode.
             * @member {number} gpsMode
             * @memberof meshtastic.Config.PositionConfig
             * @instance
             */
            PositionConfig.prototype.gpsMode = 0;

            /**
             * Creates a new PositionConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.Config.PositionConfig
             * @static
             * @param {meshtastic.Config.IPositionConfig=} [properties] Properties to set
             * @returns {meshtastic.Config.PositionConfig} PositionConfig instance
             */
            PositionConfig.create = function create(properties) {
                return new PositionConfig(properties);
            };

            /**
             * Encodes the specified PositionConfig message. Does not implicitly {@link meshtastic.Config.PositionConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.Config.PositionConfig
             * @static
             * @param {meshtastic.Config.IPositionConfig} message PositionConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            PositionConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.positionBroadcastSecs != null && Object.hasOwnProperty.call(message, "positionBroadcastSecs"))
                    writer.uint32(/* id 1, wireType 0 =*/8).uint32(message.positionBroadcastSecs);
                if (message.positionBroadcastSmartEnabled != null && Object.hasOwnProperty.call(message, "positionBroadcastSmartEnabled"))
                    writer.uint32(/* id 2, wireType 0 =*/16).bool(message.positionBroadcastSmartEnabled);
                if (message.fixedPosition != null && Object.hasOwnProperty.call(message, "fixedPosition"))
                    writer.uint32(/* id 3, wireType 0 =*/24).bool(message.fixedPosition);
                if (message.gpsEnabled != null && Object.hasOwnProperty.call(message, "gpsEnabled"))
                    writer.uint32(/* id 4, wireType 0 =*/32).bool(message.gpsEnabled);
                if (message.gpsUpdateInterval != null && Object.hasOwnProperty.call(message, "gpsUpdateInterval"))
                    writer.uint32(/* id 5, wireType 0 =*/40).uint32(message.gpsUpdateInterval);
                if (message.gpsAttemptTime != null && Object.hasOwnProperty.call(message, "gpsAttemptTime"))
                    writer.uint32(/* id 6, wireType 0 =*/48).uint32(message.gpsAttemptTime);
                if (message.positionFlags != null && Object.hasOwnProperty.call(message, "positionFlags"))
                    writer.uint32(/* id 7, wireType 0 =*/56).uint32(message.positionFlags);
                if (message.rxGpio != null && Object.hasOwnProperty.call(message, "rxGpio"))
                    writer.uint32(/* id 8, wireType 0 =*/64).uint32(message.rxGpio);
                if (message.txGpio != null && Object.hasOwnProperty.call(message, "txGpio"))
                    writer.uint32(/* id 9, wireType 0 =*/72).uint32(message.txGpio);
                if (message.broadcastSmartMinimumDistance != null && Object.hasOwnProperty.call(message, "broadcastSmartMinimumDistance"))
                    writer.uint32(/* id 10, wireType 0 =*/80).uint32(message.broadcastSmartMinimumDistance);
                if (message.broadcastSmartMinimumIntervalSecs != null && Object.hasOwnProperty.call(message, "broadcastSmartMinimumIntervalSecs"))
                    writer.uint32(/* id 11, wireType 0 =*/88).uint32(message.broadcastSmartMinimumIntervalSecs);
                if (message.gpsEnGpio != null && Object.hasOwnProperty.call(message, "gpsEnGpio"))
                    writer.uint32(/* id 12, wireType 0 =*/96).uint32(message.gpsEnGpio);
                if (message.gpsMode != null && Object.hasOwnProperty.call(message, "gpsMode"))
                    writer.uint32(/* id 13, wireType 0 =*/104).uint32(message.gpsMode);
                return writer;
            };

            /**
             * Decodes a PositionConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.Config.PositionConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.Config.PositionConfig} PositionConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            PositionConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.Config.PositionConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.positionBroadcastSecs = reader.uint32();
                            break;
                        }
                    case 2: {
                            message.positionBroadcastSmartEnabled = reader.bool();
                            break;
                        }
                    case 3: {
                            message.fixedPosition = reader.bool();
                            break;
                        }
                    case 4: {
                            message.gpsEnabled = reader.bool();
                            break;
                        }
                    case 5: {
                            message.gpsUpdateInterval = reader.uint32();
                            break;
                        }
                    case 6: {
                            message.gpsAttemptTime = reader.uint32();
                            break;
                        }
                    case 7: {
                            message.positionFlags = reader.uint32();
                            break;
                        }
                    case 8: {
                            message.rxGpio = reader.uint32();
                            break;
                        }
                    case 9: {
                            message.txGpio = reader.uint32();
                            break;
                        }
                    case 10: {
                            message.broadcastSmartMinimumDistance = reader.uint32();
                            break;
                        }
                    case 11: {
                            message.broadcastSmartMinimumIntervalSecs = reader.uint32();
                            break;
                        }
                    case 12: {
                            message.gpsEnGpio = reader.uint32();
                            break;
                        }
                    case 13: {
                            message.gpsMode = reader.uint32();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a PositionConfig message.
             * @function verify
             * @memberof meshtastic.Config.PositionConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            PositionConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.positionBroadcastSecs != null && Object.hasOwnProperty.call(message, "positionBroadcastSecs"))
                    if (!$util.isInteger(message.positionBroadcastSecs))
                        return "positionBroadcastSecs: integer expected";
                if (message.positionBroadcastSmartEnabled != null && Object.hasOwnProperty.call(message, "positionBroadcastSmartEnabled"))
                    if (typeof message.positionBroadcastSmartEnabled !== "boolean")
                        return "positionBroadcastSmartEnabled: boolean expected";
                if (message.fixedPosition != null && Object.hasOwnProperty.call(message, "fixedPosition"))
                    if (typeof message.fixedPosition !== "boolean")
                        return "fixedPosition: boolean expected";
                if (message.gpsEnabled != null && Object.hasOwnProperty.call(message, "gpsEnabled"))
                    if (typeof message.gpsEnabled !== "boolean")
                        return "gpsEnabled: boolean expected";
                if (message.gpsUpdateInterval != null && Object.hasOwnProperty.call(message, "gpsUpdateInterval"))
                    if (!$util.isInteger(message.gpsUpdateInterval))
                        return "gpsUpdateInterval: integer expected";
                if (message.gpsAttemptTime != null && Object.hasOwnProperty.call(message, "gpsAttemptTime"))
                    if (!$util.isInteger(message.gpsAttemptTime))
                        return "gpsAttemptTime: integer expected";
                if (message.positionFlags != null && Object.hasOwnProperty.call(message, "positionFlags"))
                    if (!$util.isInteger(message.positionFlags))
                        return "positionFlags: integer expected";
                if (message.rxGpio != null && Object.hasOwnProperty.call(message, "rxGpio"))
                    if (!$util.isInteger(message.rxGpio))
                        return "rxGpio: integer expected";
                if (message.txGpio != null && Object.hasOwnProperty.call(message, "txGpio"))
                    if (!$util.isInteger(message.txGpio))
                        return "txGpio: integer expected";
                if (message.broadcastSmartMinimumDistance != null && Object.hasOwnProperty.call(message, "broadcastSmartMinimumDistance"))
                    if (!$util.isInteger(message.broadcastSmartMinimumDistance))
                        return "broadcastSmartMinimumDistance: integer expected";
                if (message.broadcastSmartMinimumIntervalSecs != null && Object.hasOwnProperty.call(message, "broadcastSmartMinimumIntervalSecs"))
                    if (!$util.isInteger(message.broadcastSmartMinimumIntervalSecs))
                        return "broadcastSmartMinimumIntervalSecs: integer expected";
                if (message.gpsEnGpio != null && Object.hasOwnProperty.call(message, "gpsEnGpio"))
                    if (!$util.isInteger(message.gpsEnGpio))
                        return "gpsEnGpio: integer expected";
                if (message.gpsMode != null && Object.hasOwnProperty.call(message, "gpsMode"))
                    if (!$util.isInteger(message.gpsMode))
                        return "gpsMode: integer expected";
                return null;
            };

            /**
             * Gets the default type url for PositionConfig
             * @function getTypeUrl
             * @memberof meshtastic.Config.PositionConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            PositionConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.Config.PositionConfig";
            };

            return PositionConfig;
        })();

        Config.PowerConfig = (function() {

            /**
             * Properties of a PowerConfig.
             * @memberof meshtastic.Config
             * @interface IPowerConfig
             * @property {boolean|null} [isPowerSaving] PowerConfig isPowerSaving
             * @property {number|null} [onBatteryShutdownAfterSecs] PowerConfig onBatteryShutdownAfterSecs
             * @property {number|null} [adcMultiplierOverride] PowerConfig adcMultiplierOverride
             * @property {number|null} [waitBluetoothSecs] PowerConfig waitBluetoothSecs
             * @property {number|null} [sdsSecs] PowerConfig sdsSecs
             * @property {number|null} [lsSecs] PowerConfig lsSecs
             * @property {number|null} [minWakeSecs] PowerConfig minWakeSecs
             * @property {number|null} [deviceBatteryInaAddress] PowerConfig deviceBatteryInaAddress
             * @property {number|Long|null} [powermonEnables] PowerConfig powermonEnables
             */

            /**
             * Constructs a new PowerConfig.
             * @memberof meshtastic.Config
             * @classdesc Represents a PowerConfig.
             * @implements IPowerConfig
             * @constructor
             * @param {meshtastic.Config.IPowerConfig=} [properties] Properties to set
             */
            function PowerConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * PowerConfig isPowerSaving.
             * @member {boolean} isPowerSaving
             * @memberof meshtastic.Config.PowerConfig
             * @instance
             */
            PowerConfig.prototype.isPowerSaving = false;

            /**
             * PowerConfig onBatteryShutdownAfterSecs.
             * @member {number} onBatteryShutdownAfterSecs
             * @memberof meshtastic.Config.PowerConfig
             * @instance
             */
            PowerConfig.prototype.onBatteryShutdownAfterSecs = 0;

            /**
             * PowerConfig adcMultiplierOverride.
             * @member {number} adcMultiplierOverride
             * @memberof meshtastic.Config.PowerConfig
             * @instance
             */
            PowerConfig.prototype.adcMultiplierOverride = 0;

            /**
             * PowerConfig waitBluetoothSecs.
             * @member {number} waitBluetoothSecs
             * @memberof meshtastic.Config.PowerConfig
             * @instance
             */
            PowerConfig.prototype.waitBluetoothSecs = 0;

            /**
             * PowerConfig sdsSecs.
             * @member {number} sdsSecs
             * @memberof meshtastic.Config.PowerConfig
             * @instance
             */
            PowerConfig.prototype.sdsSecs = 0;

            /**
             * PowerConfig lsSecs.
             * @member {number} lsSecs
             * @memberof meshtastic.Config.PowerConfig
             * @instance
             */
            PowerConfig.prototype.lsSecs = 0;

            /**
             * PowerConfig minWakeSecs.
             * @member {number} minWakeSecs
             * @memberof meshtastic.Config.PowerConfig
             * @instance
             */
            PowerConfig.prototype.minWakeSecs = 0;

            /**
             * PowerConfig deviceBatteryInaAddress.
             * @member {number} deviceBatteryInaAddress
             * @memberof meshtastic.Config.PowerConfig
             * @instance
             */
            PowerConfig.prototype.deviceBatteryInaAddress = 0;

            /**
             * PowerConfig powermonEnables.
             * @member {number|Long} powermonEnables
             * @memberof meshtastic.Config.PowerConfig
             * @instance
             */
            PowerConfig.prototype.powermonEnables = $util.Long ? $util.Long.fromBits(0,0,true) : 0;

            /**
             * Creates a new PowerConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.Config.PowerConfig
             * @static
             * @param {meshtastic.Config.IPowerConfig=} [properties] Properties to set
             * @returns {meshtastic.Config.PowerConfig} PowerConfig instance
             */
            PowerConfig.create = function create(properties) {
                return new PowerConfig(properties);
            };

            /**
             * Encodes the specified PowerConfig message. Does not implicitly {@link meshtastic.Config.PowerConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.Config.PowerConfig
             * @static
             * @param {meshtastic.Config.IPowerConfig} message PowerConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            PowerConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.isPowerSaving != null && Object.hasOwnProperty.call(message, "isPowerSaving"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.isPowerSaving);
                if (message.onBatteryShutdownAfterSecs != null && Object.hasOwnProperty.call(message, "onBatteryShutdownAfterSecs"))
                    writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.onBatteryShutdownAfterSecs);
                if (message.adcMultiplierOverride != null && Object.hasOwnProperty.call(message, "adcMultiplierOverride"))
                    writer.uint32(/* id 3, wireType 5 =*/29).float(message.adcMultiplierOverride);
                if (message.waitBluetoothSecs != null && Object.hasOwnProperty.call(message, "waitBluetoothSecs"))
                    writer.uint32(/* id 4, wireType 0 =*/32).uint32(message.waitBluetoothSecs);
                if (message.sdsSecs != null && Object.hasOwnProperty.call(message, "sdsSecs"))
                    writer.uint32(/* id 6, wireType 0 =*/48).uint32(message.sdsSecs);
                if (message.lsSecs != null && Object.hasOwnProperty.call(message, "lsSecs"))
                    writer.uint32(/* id 7, wireType 0 =*/56).uint32(message.lsSecs);
                if (message.minWakeSecs != null && Object.hasOwnProperty.call(message, "minWakeSecs"))
                    writer.uint32(/* id 8, wireType 0 =*/64).uint32(message.minWakeSecs);
                if (message.deviceBatteryInaAddress != null && Object.hasOwnProperty.call(message, "deviceBatteryInaAddress"))
                    writer.uint32(/* id 9, wireType 0 =*/72).uint32(message.deviceBatteryInaAddress);
                if (message.powermonEnables != null && Object.hasOwnProperty.call(message, "powermonEnables"))
                    writer.uint32(/* id 32, wireType 0 =*/256).uint64(message.powermonEnables);
                return writer;
            };

            /**
             * Decodes a PowerConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.Config.PowerConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.Config.PowerConfig} PowerConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            PowerConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.Config.PowerConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.isPowerSaving = reader.bool();
                            break;
                        }
                    case 2: {
                            message.onBatteryShutdownAfterSecs = reader.uint32();
                            break;
                        }
                    case 3: {
                            message.adcMultiplierOverride = reader.float();
                            break;
                        }
                    case 4: {
                            message.waitBluetoothSecs = reader.uint32();
                            break;
                        }
                    case 6: {
                            message.sdsSecs = reader.uint32();
                            break;
                        }
                    case 7: {
                            message.lsSecs = reader.uint32();
                            break;
                        }
                    case 8: {
                            message.minWakeSecs = reader.uint32();
                            break;
                        }
                    case 9: {
                            message.deviceBatteryInaAddress = reader.uint32();
                            break;
                        }
                    case 32: {
                            message.powermonEnables = reader.uint64();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a PowerConfig message.
             * @function verify
             * @memberof meshtastic.Config.PowerConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            PowerConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.isPowerSaving != null && Object.hasOwnProperty.call(message, "isPowerSaving"))
                    if (typeof message.isPowerSaving !== "boolean")
                        return "isPowerSaving: boolean expected";
                if (message.onBatteryShutdownAfterSecs != null && Object.hasOwnProperty.call(message, "onBatteryShutdownAfterSecs"))
                    if (!$util.isInteger(message.onBatteryShutdownAfterSecs))
                        return "onBatteryShutdownAfterSecs: integer expected";
                if (message.adcMultiplierOverride != null && Object.hasOwnProperty.call(message, "adcMultiplierOverride"))
                    if (typeof message.adcMultiplierOverride !== "number")
                        return "adcMultiplierOverride: number expected";
                if (message.waitBluetoothSecs != null && Object.hasOwnProperty.call(message, "waitBluetoothSecs"))
                    if (!$util.isInteger(message.waitBluetoothSecs))
                        return "waitBluetoothSecs: integer expected";
                if (message.sdsSecs != null && Object.hasOwnProperty.call(message, "sdsSecs"))
                    if (!$util.isInteger(message.sdsSecs))
                        return "sdsSecs: integer expected";
                if (message.lsSecs != null && Object.hasOwnProperty.call(message, "lsSecs"))
                    if (!$util.isInteger(message.lsSecs))
                        return "lsSecs: integer expected";
                if (message.minWakeSecs != null && Object.hasOwnProperty.call(message, "minWakeSecs"))
                    if (!$util.isInteger(message.minWakeSecs))
                        return "minWakeSecs: integer expected";
                if (message.deviceBatteryInaAddress != null && Object.hasOwnProperty.call(message, "deviceBatteryInaAddress"))
                    if (!$util.isInteger(message.deviceBatteryInaAddress))
                        return "deviceBatteryInaAddress: integer expected";
                if (message.powermonEnables != null && Object.hasOwnProperty.call(message, "powermonEnables"))
                    if (!$util.isInteger(message.powermonEnables) && !(message.powermonEnables && $util.isInteger(message.powermonEnables.low) && $util.isInteger(message.powermonEnables.high)))
                        return "powermonEnables: integer|Long expected";
                return null;
            };

            /**
             * Gets the default type url for PowerConfig
             * @function getTypeUrl
             * @memberof meshtastic.Config.PowerConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            PowerConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.Config.PowerConfig";
            };

            return PowerConfig;
        })();

        Config.NetworkConfig = (function() {

            /**
             * Properties of a NetworkConfig.
             * @memberof meshtastic.Config
             * @interface INetworkConfig
             * @property {boolean|null} [wifiEnabled] NetworkConfig wifiEnabled
             * @property {string|null} [wifiSsid] NetworkConfig wifiSsid
             * @property {string|null} [wifiPsk] NetworkConfig wifiPsk
             * @property {string|null} [ntpServer] NetworkConfig ntpServer
             * @property {boolean|null} [ethEnabled] NetworkConfig ethEnabled
             * @property {number|null} [addressMode] NetworkConfig addressMode
             */

            /**
             * Constructs a new NetworkConfig.
             * @memberof meshtastic.Config
             * @classdesc Represents a NetworkConfig.
             * @implements INetworkConfig
             * @constructor
             * @param {meshtastic.Config.INetworkConfig=} [properties] Properties to set
             */
            function NetworkConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * NetworkConfig wifiEnabled.
             * @member {boolean} wifiEnabled
             * @memberof meshtastic.Config.NetworkConfig
             * @instance
             */
            NetworkConfig.prototype.wifiEnabled = false;

            /**
             * NetworkConfig wifiSsid.
             * @member {string} wifiSsid
             * @memberof meshtastic.Config.NetworkConfig
             * @instance
             */
            NetworkConfig.prototype.wifiSsid = "";

            /**
             * NetworkConfig wifiPsk.
             * @member {string} wifiPsk
             * @memberof meshtastic.Config.NetworkConfig
             * @instance
             */
            NetworkConfig.prototype.wifiPsk = "";

            /**
             * NetworkConfig ntpServer.
             * @member {string} ntpServer
             * @memberof meshtastic.Config.NetworkConfig
             * @instance
             */
            NetworkConfig.prototype.ntpServer = "";

            /**
             * NetworkConfig ethEnabled.
             * @member {boolean} ethEnabled
             * @memberof meshtastic.Config.NetworkConfig
             * @instance
             */
            NetworkConfig.prototype.ethEnabled = false;

            /**
             * NetworkConfig addressMode.
             * @member {number} addressMode
             * @memberof meshtastic.Config.NetworkConfig
             * @instance
             */
            NetworkConfig.prototype.addressMode = 0;

            /**
             * Creates a new NetworkConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.Config.NetworkConfig
             * @static
             * @param {meshtastic.Config.INetworkConfig=} [properties] Properties to set
             * @returns {meshtastic.Config.NetworkConfig} NetworkConfig instance
             */
            NetworkConfig.create = function create(properties) {
                return new NetworkConfig(properties);
            };

            /**
             * Encodes the specified NetworkConfig message. Does not implicitly {@link meshtastic.Config.NetworkConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.Config.NetworkConfig
             * @static
             * @param {meshtastic.Config.INetworkConfig} message NetworkConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            NetworkConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.wifiEnabled != null && Object.hasOwnProperty.call(message, "wifiEnabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.wifiEnabled);
                if (message.wifiSsid != null && Object.hasOwnProperty.call(message, "wifiSsid"))
                    writer.uint32(/* id 3, wireType 2 =*/26).string(message.wifiSsid);
                if (message.wifiPsk != null && Object.hasOwnProperty.call(message, "wifiPsk"))
                    writer.uint32(/* id 4, wireType 2 =*/34).string(message.wifiPsk);
                if (message.ntpServer != null && Object.hasOwnProperty.call(message, "ntpServer"))
                    writer.uint32(/* id 5, wireType 2 =*/42).string(message.ntpServer);
                if (message.ethEnabled != null && Object.hasOwnProperty.call(message, "ethEnabled"))
                    writer.uint32(/* id 6, wireType 0 =*/48).bool(message.ethEnabled);
                if (message.addressMode != null && Object.hasOwnProperty.call(message, "addressMode"))
                    writer.uint32(/* id 7, wireType 0 =*/56).uint32(message.addressMode);
                return writer;
            };

            /**
             * Decodes a NetworkConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.Config.NetworkConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.Config.NetworkConfig} NetworkConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            NetworkConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.Config.NetworkConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.wifiEnabled = reader.bool();
                            break;
                        }
                    case 3: {
                            message.wifiSsid = reader.string();
                            break;
                        }
                    case 4: {
                            message.wifiPsk = reader.string();
                            break;
                        }
                    case 5: {
                            message.ntpServer = reader.string();
                            break;
                        }
                    case 6: {
                            message.ethEnabled = reader.bool();
                            break;
                        }
                    case 7: {
                            message.addressMode = reader.uint32();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a NetworkConfig message.
             * @function verify
             * @memberof meshtastic.Config.NetworkConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            NetworkConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.wifiEnabled != null && Object.hasOwnProperty.call(message, "wifiEnabled"))
                    if (typeof message.wifiEnabled !== "boolean")
                        return "wifiEnabled: boolean expected";
                if (message.wifiSsid != null && Object.hasOwnProperty.call(message, "wifiSsid"))
                    if (!$util.isString(message.wifiSsid))
                        return "wifiSsid: string expected";
                if (message.wifiPsk != null && Object.hasOwnProperty.call(message, "wifiPsk"))
                    if (!$util.isString(message.wifiPsk))
                        return "wifiPsk: string expected";
                if (message.ntpServer != null && Object.hasOwnProperty.call(message, "ntpServer"))
                    if (!$util.isString(message.ntpServer))
                        return "ntpServer: string expected";
                if (message.ethEnabled != null && Object.hasOwnProperty.call(message, "ethEnabled"))
                    if (typeof message.ethEnabled !== "boolean")
                        return "ethEnabled: boolean expected";
                if (message.addressMode != null && Object.hasOwnProperty.call(message, "addressMode"))
                    if (!$util.isInteger(message.addressMode))
                        return "addressMode: integer expected";
                return null;
            };

            /**
             * Gets the default type url for NetworkConfig
             * @function getTypeUrl
             * @memberof meshtastic.Config.NetworkConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            NetworkConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.Config.NetworkConfig";
            };

            return NetworkConfig;
        })();

        Config.DisplayConfig = (function() {

            /**
             * Properties of a DisplayConfig.
             * @memberof meshtastic.Config
             * @interface IDisplayConfig
             * @property {number|null} [screenOnSecs] DisplayConfig screenOnSecs
             * @property {number|null} [autoScreenCarouselSecs] DisplayConfig autoScreenCarouselSecs
             * @property {boolean|null} [flipScreen] DisplayConfig flipScreen
             * @property {number|null} [units] DisplayConfig units
             * @property {number|null} [oled] DisplayConfig oled
             * @property {number|null} [displaymode] DisplayConfig displaymode
             * @property {boolean|null} [headingBold] DisplayConfig headingBold
             * @property {boolean|null} [wakeOnTapOrMotion] DisplayConfig wakeOnTapOrMotion
             */

            /**
             * Constructs a new DisplayConfig.
             * @memberof meshtastic.Config
             * @classdesc Represents a DisplayConfig.
             * @implements IDisplayConfig
             * @constructor
             * @param {meshtastic.Config.IDisplayConfig=} [properties] Properties to set
             */
            function DisplayConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * DisplayConfig screenOnSecs.
             * @member {number} screenOnSecs
             * @memberof meshtastic.Config.DisplayConfig
             * @instance
             */
            DisplayConfig.prototype.screenOnSecs = 0;

            /**
             * DisplayConfig autoScreenCarouselSecs.
             * @member {number} autoScreenCarouselSecs
             * @memberof meshtastic.Config.DisplayConfig
             * @instance
             */
            DisplayConfig.prototype.autoScreenCarouselSecs = 0;

            /**
             * DisplayConfig flipScreen.
             * @member {boolean} flipScreen
             * @memberof meshtastic.Config.DisplayConfig
             * @instance
             */
            DisplayConfig.prototype.flipScreen = false;

            /**
             * DisplayConfig units.
             * @member {number} units
             * @memberof meshtastic.Config.DisplayConfig
             * @instance
             */
            DisplayConfig.prototype.units = 0;

            /**
             * DisplayConfig oled.
             * @member {number} oled
             * @memberof meshtastic.Config.DisplayConfig
             * @instance
             */
            DisplayConfig.prototype.oled = 0;

            /**
             * DisplayConfig displaymode.
             * @member {number} displaymode
             * @memberof meshtastic.Config.DisplayConfig
             * @instance
             */
            DisplayConfig.prototype.displaymode = 0;

            /**
             * DisplayConfig headingBold.
             * @member {boolean} headingBold
             * @memberof meshtastic.Config.DisplayConfig
             * @instance
             */
            DisplayConfig.prototype.headingBold = false;

            /**
             * DisplayConfig wakeOnTapOrMotion.
             * @member {boolean} wakeOnTapOrMotion
             * @memberof meshtastic.Config.DisplayConfig
             * @instance
             */
            DisplayConfig.prototype.wakeOnTapOrMotion = false;

            /**
             * Creates a new DisplayConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.Config.DisplayConfig
             * @static
             * @param {meshtastic.Config.IDisplayConfig=} [properties] Properties to set
             * @returns {meshtastic.Config.DisplayConfig} DisplayConfig instance
             */
            DisplayConfig.create = function create(properties) {
                return new DisplayConfig(properties);
            };

            /**
             * Encodes the specified DisplayConfig message. Does not implicitly {@link meshtastic.Config.DisplayConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.Config.DisplayConfig
             * @static
             * @param {meshtastic.Config.IDisplayConfig} message DisplayConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            DisplayConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.screenOnSecs != null && Object.hasOwnProperty.call(message, "screenOnSecs"))
                    writer.uint32(/* id 1, wireType 0 =*/8).uint32(message.screenOnSecs);
                if (message.autoScreenCarouselSecs != null && Object.hasOwnProperty.call(message, "autoScreenCarouselSecs"))
                    writer.uint32(/* id 3, wireType 0 =*/24).uint32(message.autoScreenCarouselSecs);
                if (message.flipScreen != null && Object.hasOwnProperty.call(message, "flipScreen"))
                    writer.uint32(/* id 5, wireType 0 =*/40).bool(message.flipScreen);
                if (message.units != null && Object.hasOwnProperty.call(message, "units"))
                    writer.uint32(/* id 6, wireType 0 =*/48).uint32(message.units);
                if (message.oled != null && Object.hasOwnProperty.call(message, "oled"))
                    writer.uint32(/* id 7, wireType 0 =*/56).uint32(message.oled);
                if (message.displaymode != null && Object.hasOwnProperty.call(message, "displaymode"))
                    writer.uint32(/* id 8, wireType 0 =*/64).uint32(message.displaymode);
                if (message.headingBold != null && Object.hasOwnProperty.call(message, "headingBold"))
                    writer.uint32(/* id 9, wireType 0 =*/72).bool(message.headingBold);
                if (message.wakeOnTapOrMotion != null && Object.hasOwnProperty.call(message, "wakeOnTapOrMotion"))
                    writer.uint32(/* id 10, wireType 0 =*/80).bool(message.wakeOnTapOrMotion);
                return writer;
            };

            /**
             * Decodes a DisplayConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.Config.DisplayConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.Config.DisplayConfig} DisplayConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            DisplayConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.Config.DisplayConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.screenOnSecs = reader.uint32();
                            break;
                        }
                    case 3: {
                            message.autoScreenCarouselSecs = reader.uint32();
                            break;
                        }
                    case 5: {
                            message.flipScreen = reader.bool();
                            break;
                        }
                    case 6: {
                            message.units = reader.uint32();
                            break;
                        }
                    case 7: {
                            message.oled = reader.uint32();
                            break;
                        }
                    case 8: {
                            message.displaymode = reader.uint32();
                            break;
                        }
                    case 9: {
                            message.headingBold = reader.bool();
                            break;
                        }
                    case 10: {
                            message.wakeOnTapOrMotion = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a DisplayConfig message.
             * @function verify
             * @memberof meshtastic.Config.DisplayConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            DisplayConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.screenOnSecs != null && Object.hasOwnProperty.call(message, "screenOnSecs"))
                    if (!$util.isInteger(message.screenOnSecs))
                        return "screenOnSecs: integer expected";
                if (message.autoScreenCarouselSecs != null && Object.hasOwnProperty.call(message, "autoScreenCarouselSecs"))
                    if (!$util.isInteger(message.autoScreenCarouselSecs))
                        return "autoScreenCarouselSecs: integer expected";
                if (message.flipScreen != null && Object.hasOwnProperty.call(message, "flipScreen"))
                    if (typeof message.flipScreen !== "boolean")
                        return "flipScreen: boolean expected";
                if (message.units != null && Object.hasOwnProperty.call(message, "units"))
                    if (!$util.isInteger(message.units))
                        return "units: integer expected";
                if (message.oled != null && Object.hasOwnProperty.call(message, "oled"))
                    if (!$util.isInteger(message.oled))
                        return "oled: integer expected";
                if (message.displaymode != null && Object.hasOwnProperty.call(message, "displaymode"))
                    if (!$util.isInteger(message.displaymode))
                        return "displaymode: integer expected";
                if (message.headingBold != null && Object.hasOwnProperty.call(message, "headingBold"))
                    if (typeof message.headingBold !== "boolean")
                        return "headingBold: boolean expected";
                if (message.wakeOnTapOrMotion != null && Object.hasOwnProperty.call(message, "wakeOnTapOrMotion"))
                    if (typeof message.wakeOnTapOrMotion !== "boolean")
                        return "wakeOnTapOrMotion: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for DisplayConfig
             * @function getTypeUrl
             * @memberof meshtastic.Config.DisplayConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            DisplayConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.Config.DisplayConfig";
            };

            return DisplayConfig;
        })();

        Config.LoRaConfig = (function() {

            /**
             * Properties of a LoRaConfig.
             * @memberof meshtastic.Config
             * @interface ILoRaConfig
             * @property {boolean|null} [usePreset] LoRaConfig usePreset
             * @property {meshtastic.Config.LoRaConfig.ModemPreset|null} [modemPreset] LoRaConfig modemPreset
             * @property {number|null} [bandwidth] LoRaConfig bandwidth
             * @property {number|null} [spreadFactor] LoRaConfig spreadFactor
             * @property {number|null} [codingRate] LoRaConfig codingRate
             * @property {number|null} [frequencyOffset] LoRaConfig frequencyOffset
             * @property {meshtastic.Config.LoRaConfig.RegionCode|null} [region] LoRaConfig region
             * @property {number|null} [hopLimit] LoRaConfig hopLimit
             * @property {boolean|null} [txEnabled] LoRaConfig txEnabled
             * @property {number|null} [txPower] LoRaConfig txPower
             * @property {number|null} [channelNum] LoRaConfig channelNum
             * @property {boolean|null} [overrideDutyCycle] LoRaConfig overrideDutyCycle
             * @property {boolean|null} [sx126xRxBoostedGain] LoRaConfig sx126xRxBoostedGain
             * @property {number|null} [overrideFrequency] LoRaConfig overrideFrequency
             * @property {boolean|null} [paFanDisabled] LoRaConfig paFanDisabled
             * @property {Array.<number>|null} [ignoreIncoming] LoRaConfig ignoreIncoming
             * @property {boolean|null} [ignoreMqtt] LoRaConfig ignoreMqtt
             * @property {boolean|null} [configOkToMqtt] LoRaConfig configOkToMqtt
             * @property {number|null} [femLnaMode] LoRaConfig femLnaMode
             */

            /**
             * Constructs a new LoRaConfig.
             * @memberof meshtastic.Config
             * @classdesc Represents a LoRaConfig.
             * @implements ILoRaConfig
             * @constructor
             * @param {meshtastic.Config.ILoRaConfig=} [properties] Properties to set
             */
            function LoRaConfig(properties) {
                this.ignoreIncoming = [];
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * LoRaConfig usePreset.
             * @member {boolean} usePreset
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.usePreset = false;

            /**
             * LoRaConfig modemPreset.
             * @member {meshtastic.Config.LoRaConfig.ModemPreset} modemPreset
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.modemPreset = 0;

            /**
             * LoRaConfig bandwidth.
             * @member {number} bandwidth
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.bandwidth = 0;

            /**
             * LoRaConfig spreadFactor.
             * @member {number} spreadFactor
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.spreadFactor = 0;

            /**
             * LoRaConfig codingRate.
             * @member {number} codingRate
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.codingRate = 0;

            /**
             * LoRaConfig frequencyOffset.
             * @member {number} frequencyOffset
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.frequencyOffset = 0;

            /**
             * LoRaConfig region.
             * @member {meshtastic.Config.LoRaConfig.RegionCode} region
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.region = 0;

            /**
             * LoRaConfig hopLimit.
             * @member {number} hopLimit
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.hopLimit = 0;

            /**
             * LoRaConfig txEnabled.
             * @member {boolean} txEnabled
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.txEnabled = false;

            /**
             * LoRaConfig txPower.
             * @member {number} txPower
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.txPower = 0;

            /**
             * LoRaConfig channelNum.
             * @member {number} channelNum
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.channelNum = 0;

            /**
             * LoRaConfig overrideDutyCycle.
             * @member {boolean} overrideDutyCycle
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.overrideDutyCycle = false;

            /**
             * LoRaConfig sx126xRxBoostedGain.
             * @member {boolean} sx126xRxBoostedGain
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.sx126xRxBoostedGain = false;

            /**
             * LoRaConfig overrideFrequency.
             * @member {number} overrideFrequency
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.overrideFrequency = 0;

            /**
             * LoRaConfig paFanDisabled.
             * @member {boolean} paFanDisabled
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.paFanDisabled = false;

            /**
             * LoRaConfig ignoreIncoming.
             * @member {Array.<number>} ignoreIncoming
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.ignoreIncoming = $util.emptyArray;

            /**
             * LoRaConfig ignoreMqtt.
             * @member {boolean} ignoreMqtt
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.ignoreMqtt = false;

            /**
             * LoRaConfig configOkToMqtt.
             * @member {boolean} configOkToMqtt
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.configOkToMqtt = false;

            /**
             * LoRaConfig femLnaMode.
             * @member {number} femLnaMode
             * @memberof meshtastic.Config.LoRaConfig
             * @instance
             */
            LoRaConfig.prototype.femLnaMode = 0;

            /**
             * Creates a new LoRaConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.Config.LoRaConfig
             * @static
             * @param {meshtastic.Config.ILoRaConfig=} [properties] Properties to set
             * @returns {meshtastic.Config.LoRaConfig} LoRaConfig instance
             */
            LoRaConfig.create = function create(properties) {
                return new LoRaConfig(properties);
            };

            /**
             * Encodes the specified LoRaConfig message. Does not implicitly {@link meshtastic.Config.LoRaConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.Config.LoRaConfig
             * @static
             * @param {meshtastic.Config.ILoRaConfig} message LoRaConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            LoRaConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.usePreset != null && Object.hasOwnProperty.call(message, "usePreset"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.usePreset);
                if (message.modemPreset != null && Object.hasOwnProperty.call(message, "modemPreset"))
                    writer.uint32(/* id 2, wireType 0 =*/16).int32(message.modemPreset);
                if (message.bandwidth != null && Object.hasOwnProperty.call(message, "bandwidth"))
                    writer.uint32(/* id 3, wireType 0 =*/24).uint32(message.bandwidth);
                if (message.spreadFactor != null && Object.hasOwnProperty.call(message, "spreadFactor"))
                    writer.uint32(/* id 4, wireType 0 =*/32).uint32(message.spreadFactor);
                if (message.codingRate != null && Object.hasOwnProperty.call(message, "codingRate"))
                    writer.uint32(/* id 5, wireType 0 =*/40).uint32(message.codingRate);
                if (message.frequencyOffset != null && Object.hasOwnProperty.call(message, "frequencyOffset"))
                    writer.uint32(/* id 6, wireType 5 =*/53).float(message.frequencyOffset);
                if (message.region != null && Object.hasOwnProperty.call(message, "region"))
                    writer.uint32(/* id 7, wireType 0 =*/56).int32(message.region);
                if (message.hopLimit != null && Object.hasOwnProperty.call(message, "hopLimit"))
                    writer.uint32(/* id 8, wireType 0 =*/64).uint32(message.hopLimit);
                if (message.txEnabled != null && Object.hasOwnProperty.call(message, "txEnabled"))
                    writer.uint32(/* id 9, wireType 0 =*/72).bool(message.txEnabled);
                if (message.txPower != null && Object.hasOwnProperty.call(message, "txPower"))
                    writer.uint32(/* id 10, wireType 0 =*/80).int32(message.txPower);
                if (message.channelNum != null && Object.hasOwnProperty.call(message, "channelNum"))
                    writer.uint32(/* id 11, wireType 0 =*/88).uint32(message.channelNum);
                if (message.overrideDutyCycle != null && Object.hasOwnProperty.call(message, "overrideDutyCycle"))
                    writer.uint32(/* id 12, wireType 0 =*/96).bool(message.overrideDutyCycle);
                if (message.sx126xRxBoostedGain != null && Object.hasOwnProperty.call(message, "sx126xRxBoostedGain"))
                    writer.uint32(/* id 13, wireType 0 =*/104).bool(message.sx126xRxBoostedGain);
                if (message.overrideFrequency != null && Object.hasOwnProperty.call(message, "overrideFrequency"))
                    writer.uint32(/* id 14, wireType 5 =*/117).float(message.overrideFrequency);
                if (message.paFanDisabled != null && Object.hasOwnProperty.call(message, "paFanDisabled"))
                    writer.uint32(/* id 15, wireType 0 =*/120).bool(message.paFanDisabled);
                if (message.ignoreIncoming != null && message.ignoreIncoming.length) {
                    writer.uint32(/* id 103, wireType 2 =*/826).fork();
                    for (let i = 0; i < message.ignoreIncoming.length; ++i)
                        writer.uint32(message.ignoreIncoming[i]);
                    writer.ldelim();
                }
                if (message.ignoreMqtt != null && Object.hasOwnProperty.call(message, "ignoreMqtt"))
                    writer.uint32(/* id 104, wireType 0 =*/832).bool(message.ignoreMqtt);
                if (message.configOkToMqtt != null && Object.hasOwnProperty.call(message, "configOkToMqtt"))
                    writer.uint32(/* id 105, wireType 0 =*/840).bool(message.configOkToMqtt);
                if (message.femLnaMode != null && Object.hasOwnProperty.call(message, "femLnaMode"))
                    writer.uint32(/* id 106, wireType 0 =*/848).uint32(message.femLnaMode);
                return writer;
            };

            /**
             * Decodes a LoRaConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.Config.LoRaConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.Config.LoRaConfig} LoRaConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            LoRaConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.Config.LoRaConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.usePreset = reader.bool();
                            break;
                        }
                    case 2: {
                            message.modemPreset = reader.int32();
                            break;
                        }
                    case 3: {
                            message.bandwidth = reader.uint32();
                            break;
                        }
                    case 4: {
                            message.spreadFactor = reader.uint32();
                            break;
                        }
                    case 5: {
                            message.codingRate = reader.uint32();
                            break;
                        }
                    case 6: {
                            message.frequencyOffset = reader.float();
                            break;
                        }
                    case 7: {
                            message.region = reader.int32();
                            break;
                        }
                    case 8: {
                            message.hopLimit = reader.uint32();
                            break;
                        }
                    case 9: {
                            message.txEnabled = reader.bool();
                            break;
                        }
                    case 10: {
                            message.txPower = reader.int32();
                            break;
                        }
                    case 11: {
                            message.channelNum = reader.uint32();
                            break;
                        }
                    case 12: {
                            message.overrideDutyCycle = reader.bool();
                            break;
                        }
                    case 13: {
                            message.sx126xRxBoostedGain = reader.bool();
                            break;
                        }
                    case 14: {
                            message.overrideFrequency = reader.float();
                            break;
                        }
                    case 15: {
                            message.paFanDisabled = reader.bool();
                            break;
                        }
                    case 103: {
                            if (!(message.ignoreIncoming && message.ignoreIncoming.length))
                                message.ignoreIncoming = [];
                            if ((tag & 7) === 2) {
                                let end2 = reader.uint32() + reader.pos;
                                while (reader.pos < end2)
                                    message.ignoreIncoming.push(reader.uint32());
                            } else
                                message.ignoreIncoming.push(reader.uint32());
                            break;
                        }
                    case 104: {
                            message.ignoreMqtt = reader.bool();
                            break;
                        }
                    case 105: {
                            message.configOkToMqtt = reader.bool();
                            break;
                        }
                    case 106: {
                            message.femLnaMode = reader.uint32();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a LoRaConfig message.
             * @function verify
             * @memberof meshtastic.Config.LoRaConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            LoRaConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.usePreset != null && Object.hasOwnProperty.call(message, "usePreset"))
                    if (typeof message.usePreset !== "boolean")
                        return "usePreset: boolean expected";
                if (message.modemPreset != null && Object.hasOwnProperty.call(message, "modemPreset"))
                    switch (message.modemPreset) {
                    default:
                        return "modemPreset: enum value expected";
                    case 0:
                    case 1:
                    case 2:
                    case 3:
                    case 4:
                    case 5:
                    case 6:
                    case 7:
                    case 8:
                    case 9:
                        break;
                    }
                if (message.bandwidth != null && Object.hasOwnProperty.call(message, "bandwidth"))
                    if (!$util.isInteger(message.bandwidth))
                        return "bandwidth: integer expected";
                if (message.spreadFactor != null && Object.hasOwnProperty.call(message, "spreadFactor"))
                    if (!$util.isInteger(message.spreadFactor))
                        return "spreadFactor: integer expected";
                if (message.codingRate != null && Object.hasOwnProperty.call(message, "codingRate"))
                    if (!$util.isInteger(message.codingRate))
                        return "codingRate: integer expected";
                if (message.frequencyOffset != null && Object.hasOwnProperty.call(message, "frequencyOffset"))
                    if (typeof message.frequencyOffset !== "number")
                        return "frequencyOffset: number expected";
                if (message.region != null && Object.hasOwnProperty.call(message, "region"))
                    switch (message.region) {
                    default:
                        return "region: enum value expected";
                    case 0:
                    case 1:
                    case 2:
                    case 3:
                    case 4:
                    case 5:
                    case 6:
                    case 7:
                    case 8:
                    case 9:
                    case 10:
                    case 11:
                    case 12:
                    case 13:
                    case 14:
                    case 15:
                    case 16:
                    case 17:
                    case 18:
                        break;
                    }
                if (message.hopLimit != null && Object.hasOwnProperty.call(message, "hopLimit"))
                    if (!$util.isInteger(message.hopLimit))
                        return "hopLimit: integer expected";
                if (message.txEnabled != null && Object.hasOwnProperty.call(message, "txEnabled"))
                    if (typeof message.txEnabled !== "boolean")
                        return "txEnabled: boolean expected";
                if (message.txPower != null && Object.hasOwnProperty.call(message, "txPower"))
                    if (!$util.isInteger(message.txPower))
                        return "txPower: integer expected";
                if (message.channelNum != null && Object.hasOwnProperty.call(message, "channelNum"))
                    if (!$util.isInteger(message.channelNum))
                        return "channelNum: integer expected";
                if (message.overrideDutyCycle != null && Object.hasOwnProperty.call(message, "overrideDutyCycle"))
                    if (typeof message.overrideDutyCycle !== "boolean")
                        return "overrideDutyCycle: boolean expected";
                if (message.sx126xRxBoostedGain != null && Object.hasOwnProperty.call(message, "sx126xRxBoostedGain"))
                    if (typeof message.sx126xRxBoostedGain !== "boolean")
                        return "sx126xRxBoostedGain: boolean expected";
                if (message.overrideFrequency != null && Object.hasOwnProperty.call(message, "overrideFrequency"))
                    if (typeof message.overrideFrequency !== "number")
                        return "overrideFrequency: number expected";
                if (message.paFanDisabled != null && Object.hasOwnProperty.call(message, "paFanDisabled"))
                    if (typeof message.paFanDisabled !== "boolean")
                        return "paFanDisabled: boolean expected";
                if (message.ignoreIncoming != null && Object.hasOwnProperty.call(message, "ignoreIncoming")) {
                    if (!Array.isArray(message.ignoreIncoming))
                        return "ignoreIncoming: array expected";
                    for (let i = 0; i < message.ignoreIncoming.length; ++i)
                        if (!$util.isInteger(message.ignoreIncoming[i]))
                            return "ignoreIncoming: integer[] expected";
                }
                if (message.ignoreMqtt != null && Object.hasOwnProperty.call(message, "ignoreMqtt"))
                    if (typeof message.ignoreMqtt !== "boolean")
                        return "ignoreMqtt: boolean expected";
                if (message.configOkToMqtt != null && Object.hasOwnProperty.call(message, "configOkToMqtt"))
                    if (typeof message.configOkToMqtt !== "boolean")
                        return "configOkToMqtt: boolean expected";
                if (message.femLnaMode != null && Object.hasOwnProperty.call(message, "femLnaMode"))
                    if (!$util.isInteger(message.femLnaMode))
                        return "femLnaMode: integer expected";
                return null;
            };

            /**
             * Gets the default type url for LoRaConfig
             * @function getTypeUrl
             * @memberof meshtastic.Config.LoRaConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            LoRaConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.Config.LoRaConfig";
            };

            /**
             * RegionCode enum.
             * @name meshtastic.Config.LoRaConfig.RegionCode
             * @enum {number}
             * @property {number} UNSET=0 UNSET value
             * @property {number} US=1 US value
             * @property {number} EU_433=2 EU_433 value
             * @property {number} EU_868=3 EU_868 value
             * @property {number} CN=4 CN value
             * @property {number} JP=5 JP value
             * @property {number} ANZ=6 ANZ value
             * @property {number} KR=7 KR value
             * @property {number} TW=8 TW value
             * @property {number} RU=9 RU value
             * @property {number} IN=10 IN value
             * @property {number} NZ_865=11 NZ_865 value
             * @property {number} TH=12 TH value
             * @property {number} LORA_24=13 LORA_24 value
             * @property {number} UA_433=14 UA_433 value
             * @property {number} UA_868=15 UA_868 value
             * @property {number} MY_433=16 MY_433 value
             * @property {number} MY_919=17 MY_919 value
             * @property {number} SG_923=18 SG_923 value
             */
            LoRaConfig.RegionCode = (function() {
                const valuesById = {}, values = Object.create(valuesById);
                values[valuesById[0] = "UNSET"] = 0;
                values[valuesById[1] = "US"] = 1;
                values[valuesById[2] = "EU_433"] = 2;
                values[valuesById[3] = "EU_868"] = 3;
                values[valuesById[4] = "CN"] = 4;
                values[valuesById[5] = "JP"] = 5;
                values[valuesById[6] = "ANZ"] = 6;
                values[valuesById[7] = "KR"] = 7;
                values[valuesById[8] = "TW"] = 8;
                values[valuesById[9] = "RU"] = 9;
                values[valuesById[10] = "IN"] = 10;
                values[valuesById[11] = "NZ_865"] = 11;
                values[valuesById[12] = "TH"] = 12;
                values[valuesById[13] = "LORA_24"] = 13;
                values[valuesById[14] = "UA_433"] = 14;
                values[valuesById[15] = "UA_868"] = 15;
                values[valuesById[16] = "MY_433"] = 16;
                values[valuesById[17] = "MY_919"] = 17;
                values[valuesById[18] = "SG_923"] = 18;
                return values;
            })();

            /**
             * ModemPreset enum.
             * @name meshtastic.Config.LoRaConfig.ModemPreset
             * @enum {number}
             * @property {number} LONG_FAST=0 LONG_FAST value
             * @property {number} LONG_SLOW=1 LONG_SLOW value
             * @property {number} VERY_LONG_SLOW=2 VERY_LONG_SLOW value
             * @property {number} MEDIUM_SLOW=3 MEDIUM_SLOW value
             * @property {number} MEDIUM_FAST=4 MEDIUM_FAST value
             * @property {number} SHORT_SLOW=5 SHORT_SLOW value
             * @property {number} SHORT_FAST=6 SHORT_FAST value
             * @property {number} LONG_MODERATE=7 LONG_MODERATE value
             * @property {number} SHORT_TURBO=8 SHORT_TURBO value
             * @property {number} LONG_TURBO=9 LONG_TURBO value
             */
            LoRaConfig.ModemPreset = (function() {
                const valuesById = {}, values = Object.create(valuesById);
                values[valuesById[0] = "LONG_FAST"] = 0;
                values[valuesById[1] = "LONG_SLOW"] = 1;
                values[valuesById[2] = "VERY_LONG_SLOW"] = 2;
                values[valuesById[3] = "MEDIUM_SLOW"] = 3;
                values[valuesById[4] = "MEDIUM_FAST"] = 4;
                values[valuesById[5] = "SHORT_SLOW"] = 5;
                values[valuesById[6] = "SHORT_FAST"] = 6;
                values[valuesById[7] = "LONG_MODERATE"] = 7;
                values[valuesById[8] = "SHORT_TURBO"] = 8;
                values[valuesById[9] = "LONG_TURBO"] = 9;
                return values;
            })();

            return LoRaConfig;
        })();

        Config.BluetoothConfig = (function() {

            /**
             * Properties of a BluetoothConfig.
             * @memberof meshtastic.Config
             * @interface IBluetoothConfig
             * @property {boolean|null} [enabled] BluetoothConfig enabled
             * @property {number|null} [mode] BluetoothConfig mode
             * @property {number|null} [fixedPin] BluetoothConfig fixedPin
             */

            /**
             * Constructs a new BluetoothConfig.
             * @memberof meshtastic.Config
             * @classdesc Represents a BluetoothConfig.
             * @implements IBluetoothConfig
             * @constructor
             * @param {meshtastic.Config.IBluetoothConfig=} [properties] Properties to set
             */
            function BluetoothConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * BluetoothConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.Config.BluetoothConfig
             * @instance
             */
            BluetoothConfig.prototype.enabled = false;

            /**
             * BluetoothConfig mode.
             * @member {number} mode
             * @memberof meshtastic.Config.BluetoothConfig
             * @instance
             */
            BluetoothConfig.prototype.mode = 0;

            /**
             * BluetoothConfig fixedPin.
             * @member {number} fixedPin
             * @memberof meshtastic.Config.BluetoothConfig
             * @instance
             */
            BluetoothConfig.prototype.fixedPin = 0;

            /**
             * Creates a new BluetoothConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.Config.BluetoothConfig
             * @static
             * @param {meshtastic.Config.IBluetoothConfig=} [properties] Properties to set
             * @returns {meshtastic.Config.BluetoothConfig} BluetoothConfig instance
             */
            BluetoothConfig.create = function create(properties) {
                return new BluetoothConfig(properties);
            };

            /**
             * Encodes the specified BluetoothConfig message. Does not implicitly {@link meshtastic.Config.BluetoothConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.Config.BluetoothConfig
             * @static
             * @param {meshtastic.Config.IBluetoothConfig} message BluetoothConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            BluetoothConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.enabled);
                if (message.mode != null && Object.hasOwnProperty.call(message, "mode"))
                    writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.mode);
                if (message.fixedPin != null && Object.hasOwnProperty.call(message, "fixedPin"))
                    writer.uint32(/* id 3, wireType 0 =*/24).uint32(message.fixedPin);
                return writer;
            };

            /**
             * Decodes a BluetoothConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.Config.BluetoothConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.Config.BluetoothConfig} BluetoothConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            BluetoothConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.Config.BluetoothConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.enabled = reader.bool();
                            break;
                        }
                    case 2: {
                            message.mode = reader.uint32();
                            break;
                        }
                    case 3: {
                            message.fixedPin = reader.uint32();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a BluetoothConfig message.
             * @function verify
             * @memberof meshtastic.Config.BluetoothConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            BluetoothConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                if (message.mode != null && Object.hasOwnProperty.call(message, "mode"))
                    if (!$util.isInteger(message.mode))
                        return "mode: integer expected";
                if (message.fixedPin != null && Object.hasOwnProperty.call(message, "fixedPin"))
                    if (!$util.isInteger(message.fixedPin))
                        return "fixedPin: integer expected";
                return null;
            };

            /**
             * Gets the default type url for BluetoothConfig
             * @function getTypeUrl
             * @memberof meshtastic.Config.BluetoothConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            BluetoothConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.Config.BluetoothConfig";
            };

            return BluetoothConfig;
        })();

        Config.SecurityConfig = (function() {

            /**
             * Properties of a SecurityConfig.
             * @memberof meshtastic.Config
             * @interface ISecurityConfig
             * @property {Uint8Array|null} [publicKey] SecurityConfig publicKey
             * @property {Uint8Array|null} [privateKey] SecurityConfig privateKey
             * @property {Array.<Uint8Array>|null} [adminKey] SecurityConfig adminKey
             * @property {boolean|null} [isManaged] SecurityConfig isManaged
             * @property {boolean|null} [serialEnabled] SecurityConfig serialEnabled
             * @property {boolean|null} [debugLogApiEnabled] SecurityConfig debugLogApiEnabled
             * @property {boolean|null} [adminChannelEnabled] SecurityConfig adminChannelEnabled
             */

            /**
             * Constructs a new SecurityConfig.
             * @memberof meshtastic.Config
             * @classdesc Represents a SecurityConfig.
             * @implements ISecurityConfig
             * @constructor
             * @param {meshtastic.Config.ISecurityConfig=} [properties] Properties to set
             */
            function SecurityConfig(properties) {
                this.adminKey = [];
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * SecurityConfig publicKey.
             * @member {Uint8Array} publicKey
             * @memberof meshtastic.Config.SecurityConfig
             * @instance
             */
            SecurityConfig.prototype.publicKey = $util.newBuffer([]);

            /**
             * SecurityConfig privateKey.
             * @member {Uint8Array} privateKey
             * @memberof meshtastic.Config.SecurityConfig
             * @instance
             */
            SecurityConfig.prototype.privateKey = $util.newBuffer([]);

            /**
             * SecurityConfig adminKey.
             * @member {Array.<Uint8Array>} adminKey
             * @memberof meshtastic.Config.SecurityConfig
             * @instance
             */
            SecurityConfig.prototype.adminKey = $util.emptyArray;

            /**
             * SecurityConfig isManaged.
             * @member {boolean} isManaged
             * @memberof meshtastic.Config.SecurityConfig
             * @instance
             */
            SecurityConfig.prototype.isManaged = false;

            /**
             * SecurityConfig serialEnabled.
             * @member {boolean} serialEnabled
             * @memberof meshtastic.Config.SecurityConfig
             * @instance
             */
            SecurityConfig.prototype.serialEnabled = false;

            /**
             * SecurityConfig debugLogApiEnabled.
             * @member {boolean} debugLogApiEnabled
             * @memberof meshtastic.Config.SecurityConfig
             * @instance
             */
            SecurityConfig.prototype.debugLogApiEnabled = false;

            /**
             * SecurityConfig adminChannelEnabled.
             * @member {boolean} adminChannelEnabled
             * @memberof meshtastic.Config.SecurityConfig
             * @instance
             */
            SecurityConfig.prototype.adminChannelEnabled = false;

            /**
             * Creates a new SecurityConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.Config.SecurityConfig
             * @static
             * @param {meshtastic.Config.ISecurityConfig=} [properties] Properties to set
             * @returns {meshtastic.Config.SecurityConfig} SecurityConfig instance
             */
            SecurityConfig.create = function create(properties) {
                return new SecurityConfig(properties);
            };

            /**
             * Encodes the specified SecurityConfig message. Does not implicitly {@link meshtastic.Config.SecurityConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.Config.SecurityConfig
             * @static
             * @param {meshtastic.Config.ISecurityConfig} message SecurityConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            SecurityConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.publicKey != null && Object.hasOwnProperty.call(message, "publicKey"))
                    writer.uint32(/* id 1, wireType 2 =*/10).bytes(message.publicKey);
                if (message.privateKey != null && Object.hasOwnProperty.call(message, "privateKey"))
                    writer.uint32(/* id 2, wireType 2 =*/18).bytes(message.privateKey);
                if (message.adminKey != null && message.adminKey.length)
                    for (let i = 0; i < message.adminKey.length; ++i)
                        writer.uint32(/* id 3, wireType 2 =*/26).bytes(message.adminKey[i]);
                if (message.isManaged != null && Object.hasOwnProperty.call(message, "isManaged"))
                    writer.uint32(/* id 4, wireType 0 =*/32).bool(message.isManaged);
                if (message.serialEnabled != null && Object.hasOwnProperty.call(message, "serialEnabled"))
                    writer.uint32(/* id 5, wireType 0 =*/40).bool(message.serialEnabled);
                if (message.debugLogApiEnabled != null && Object.hasOwnProperty.call(message, "debugLogApiEnabled"))
                    writer.uint32(/* id 6, wireType 0 =*/48).bool(message.debugLogApiEnabled);
                if (message.adminChannelEnabled != null && Object.hasOwnProperty.call(message, "adminChannelEnabled"))
                    writer.uint32(/* id 8, wireType 0 =*/64).bool(message.adminChannelEnabled);
                return writer;
            };

            /**
             * Decodes a SecurityConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.Config.SecurityConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.Config.SecurityConfig} SecurityConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            SecurityConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.Config.SecurityConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.publicKey = reader.bytes();
                            break;
                        }
                    case 2: {
                            message.privateKey = reader.bytes();
                            break;
                        }
                    case 3: {
                            if (!(message.adminKey && message.adminKey.length))
                                message.adminKey = [];
                            message.adminKey.push(reader.bytes());
                            break;
                        }
                    case 4: {
                            message.isManaged = reader.bool();
                            break;
                        }
                    case 5: {
                            message.serialEnabled = reader.bool();
                            break;
                        }
                    case 6: {
                            message.debugLogApiEnabled = reader.bool();
                            break;
                        }
                    case 8: {
                            message.adminChannelEnabled = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a SecurityConfig message.
             * @function verify
             * @memberof meshtastic.Config.SecurityConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            SecurityConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.publicKey != null && Object.hasOwnProperty.call(message, "publicKey"))
                    if (!(message.publicKey && typeof message.publicKey.length === "number" || $util.isString(message.publicKey)))
                        return "publicKey: buffer expected";
                if (message.privateKey != null && Object.hasOwnProperty.call(message, "privateKey"))
                    if (!(message.privateKey && typeof message.privateKey.length === "number" || $util.isString(message.privateKey)))
                        return "privateKey: buffer expected";
                if (message.adminKey != null && Object.hasOwnProperty.call(message, "adminKey")) {
                    if (!Array.isArray(message.adminKey))
                        return "adminKey: array expected";
                    for (let i = 0; i < message.adminKey.length; ++i)
                        if (!(message.adminKey[i] && typeof message.adminKey[i].length === "number" || $util.isString(message.adminKey[i])))
                            return "adminKey: buffer[] expected";
                }
                if (message.isManaged != null && Object.hasOwnProperty.call(message, "isManaged"))
                    if (typeof message.isManaged !== "boolean")
                        return "isManaged: boolean expected";
                if (message.serialEnabled != null && Object.hasOwnProperty.call(message, "serialEnabled"))
                    if (typeof message.serialEnabled !== "boolean")
                        return "serialEnabled: boolean expected";
                if (message.debugLogApiEnabled != null && Object.hasOwnProperty.call(message, "debugLogApiEnabled"))
                    if (typeof message.debugLogApiEnabled !== "boolean")
                        return "debugLogApiEnabled: boolean expected";
                if (message.adminChannelEnabled != null && Object.hasOwnProperty.call(message, "adminChannelEnabled"))
                    if (typeof message.adminChannelEnabled !== "boolean")
                        return "adminChannelEnabled: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for SecurityConfig
             * @function getTypeUrl
             * @memberof meshtastic.Config.SecurityConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            SecurityConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.Config.SecurityConfig";
            };

            return SecurityConfig;
        })();

        return Config;
    })();

    meshtastic.ModuleConfig = (function() {

        /**
         * Namespace ModuleConfig.
         * @memberof meshtastic
         * @namespace
         */
        const ModuleConfig = {};

        ModuleConfig.MapReportSettings = (function() {

            /**
             * Properties of a MapReportSettings.
             * @memberof meshtastic.ModuleConfig
             * @interface IMapReportSettings
             * @property {number|null} [publishIntervalSecs] MapReportSettings publishIntervalSecs
             * @property {number|null} [positionPrecision] MapReportSettings positionPrecision
             * @property {boolean|null} [shouldReportLocation] MapReportSettings shouldReportLocation
             */

            /**
             * Constructs a new MapReportSettings.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a MapReportSettings.
             * @implements IMapReportSettings
             * @constructor
             * @param {meshtastic.ModuleConfig.IMapReportSettings=} [properties] Properties to set
             */
            function MapReportSettings(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * MapReportSettings publishIntervalSecs.
             * @member {number} publishIntervalSecs
             * @memberof meshtastic.ModuleConfig.MapReportSettings
             * @instance
             */
            MapReportSettings.prototype.publishIntervalSecs = 0;

            /**
             * MapReportSettings positionPrecision.
             * @member {number} positionPrecision
             * @memberof meshtastic.ModuleConfig.MapReportSettings
             * @instance
             */
            MapReportSettings.prototype.positionPrecision = 0;

            /**
             * MapReportSettings shouldReportLocation.
             * @member {boolean} shouldReportLocation
             * @memberof meshtastic.ModuleConfig.MapReportSettings
             * @instance
             */
            MapReportSettings.prototype.shouldReportLocation = false;

            /**
             * Creates a new MapReportSettings instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.MapReportSettings
             * @static
             * @param {meshtastic.ModuleConfig.IMapReportSettings=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.MapReportSettings} MapReportSettings instance
             */
            MapReportSettings.create = function create(properties) {
                return new MapReportSettings(properties);
            };

            /**
             * Encodes the specified MapReportSettings message. Does not implicitly {@link meshtastic.ModuleConfig.MapReportSettings.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.MapReportSettings
             * @static
             * @param {meshtastic.ModuleConfig.IMapReportSettings} message MapReportSettings message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            MapReportSettings.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.publishIntervalSecs != null && Object.hasOwnProperty.call(message, "publishIntervalSecs"))
                    writer.uint32(/* id 1, wireType 0 =*/8).uint32(message.publishIntervalSecs);
                if (message.positionPrecision != null && Object.hasOwnProperty.call(message, "positionPrecision"))
                    writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.positionPrecision);
                if (message.shouldReportLocation != null && Object.hasOwnProperty.call(message, "shouldReportLocation"))
                    writer.uint32(/* id 3, wireType 0 =*/24).bool(message.shouldReportLocation);
                return writer;
            };

            /**
             * Decodes a MapReportSettings message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.MapReportSettings
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.MapReportSettings} MapReportSettings
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            MapReportSettings.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.MapReportSettings();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.publishIntervalSecs = reader.uint32();
                            break;
                        }
                    case 2: {
                            message.positionPrecision = reader.uint32();
                            break;
                        }
                    case 3: {
                            message.shouldReportLocation = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a MapReportSettings message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.MapReportSettings
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            MapReportSettings.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.publishIntervalSecs != null && Object.hasOwnProperty.call(message, "publishIntervalSecs"))
                    if (!$util.isInteger(message.publishIntervalSecs))
                        return "publishIntervalSecs: integer expected";
                if (message.positionPrecision != null && Object.hasOwnProperty.call(message, "positionPrecision"))
                    if (!$util.isInteger(message.positionPrecision))
                        return "positionPrecision: integer expected";
                if (message.shouldReportLocation != null && Object.hasOwnProperty.call(message, "shouldReportLocation"))
                    if (typeof message.shouldReportLocation !== "boolean")
                        return "shouldReportLocation: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for MapReportSettings
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.MapReportSettings
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            MapReportSettings.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.MapReportSettings";
            };

            return MapReportSettings;
        })();

        ModuleConfig.MQTTConfig = (function() {

            /**
             * Properties of a MQTTConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface IMQTTConfig
             * @property {boolean|null} [enabled] MQTTConfig enabled
             * @property {string|null} [address] MQTTConfig address
             * @property {string|null} [username] MQTTConfig username
             * @property {string|null} [password] MQTTConfig password
             * @property {boolean|null} [encryptionEnabled] MQTTConfig encryptionEnabled
             * @property {boolean|null} [jsonEnabled] MQTTConfig jsonEnabled
             * @property {boolean|null} [tlsEnabled] MQTTConfig tlsEnabled
             * @property {string|null} [root] MQTTConfig root
             * @property {boolean|null} [proxyToClientEnabled] MQTTConfig proxyToClientEnabled
             * @property {boolean|null} [mapReportingEnabled] MQTTConfig mapReportingEnabled
             * @property {meshtastic.ModuleConfig.IMapReportSettings|null} [mapReportSettings] MQTTConfig mapReportSettings
             */

            /**
             * Constructs a new MQTTConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a MQTTConfig.
             * @implements IMQTTConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.IMQTTConfig=} [properties] Properties to set
             */
            function MQTTConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * MQTTConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @instance
             */
            MQTTConfig.prototype.enabled = false;

            /**
             * MQTTConfig address.
             * @member {string} address
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @instance
             */
            MQTTConfig.prototype.address = "";

            /**
             * MQTTConfig username.
             * @member {string} username
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @instance
             */
            MQTTConfig.prototype.username = "";

            /**
             * MQTTConfig password.
             * @member {string} password
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @instance
             */
            MQTTConfig.prototype.password = "";

            /**
             * MQTTConfig encryptionEnabled.
             * @member {boolean} encryptionEnabled
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @instance
             */
            MQTTConfig.prototype.encryptionEnabled = false;

            /**
             * MQTTConfig jsonEnabled.
             * @member {boolean} jsonEnabled
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @instance
             */
            MQTTConfig.prototype.jsonEnabled = false;

            /**
             * MQTTConfig tlsEnabled.
             * @member {boolean} tlsEnabled
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @instance
             */
            MQTTConfig.prototype.tlsEnabled = false;

            /**
             * MQTTConfig root.
             * @member {string} root
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @instance
             */
            MQTTConfig.prototype.root = "";

            /**
             * MQTTConfig proxyToClientEnabled.
             * @member {boolean} proxyToClientEnabled
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @instance
             */
            MQTTConfig.prototype.proxyToClientEnabled = false;

            /**
             * MQTTConfig mapReportingEnabled.
             * @member {boolean} mapReportingEnabled
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @instance
             */
            MQTTConfig.prototype.mapReportingEnabled = false;

            /**
             * MQTTConfig mapReportSettings.
             * @member {meshtastic.ModuleConfig.IMapReportSettings|null|undefined} mapReportSettings
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @instance
             */
            MQTTConfig.prototype.mapReportSettings = null;

            /**
             * Creates a new MQTTConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @static
             * @param {meshtastic.ModuleConfig.IMQTTConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.MQTTConfig} MQTTConfig instance
             */
            MQTTConfig.create = function create(properties) {
                return new MQTTConfig(properties);
            };

            /**
             * Encodes the specified MQTTConfig message. Does not implicitly {@link meshtastic.ModuleConfig.MQTTConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @static
             * @param {meshtastic.ModuleConfig.IMQTTConfig} message MQTTConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            MQTTConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.enabled);
                if (message.address != null && Object.hasOwnProperty.call(message, "address"))
                    writer.uint32(/* id 2, wireType 2 =*/18).string(message.address);
                if (message.username != null && Object.hasOwnProperty.call(message, "username"))
                    writer.uint32(/* id 3, wireType 2 =*/26).string(message.username);
                if (message.password != null && Object.hasOwnProperty.call(message, "password"))
                    writer.uint32(/* id 4, wireType 2 =*/34).string(message.password);
                if (message.encryptionEnabled != null && Object.hasOwnProperty.call(message, "encryptionEnabled"))
                    writer.uint32(/* id 5, wireType 0 =*/40).bool(message.encryptionEnabled);
                if (message.jsonEnabled != null && Object.hasOwnProperty.call(message, "jsonEnabled"))
                    writer.uint32(/* id 6, wireType 0 =*/48).bool(message.jsonEnabled);
                if (message.tlsEnabled != null && Object.hasOwnProperty.call(message, "tlsEnabled"))
                    writer.uint32(/* id 7, wireType 0 =*/56).bool(message.tlsEnabled);
                if (message.root != null && Object.hasOwnProperty.call(message, "root"))
                    writer.uint32(/* id 8, wireType 2 =*/66).string(message.root);
                if (message.proxyToClientEnabled != null && Object.hasOwnProperty.call(message, "proxyToClientEnabled"))
                    writer.uint32(/* id 9, wireType 0 =*/72).bool(message.proxyToClientEnabled);
                if (message.mapReportingEnabled != null && Object.hasOwnProperty.call(message, "mapReportingEnabled"))
                    writer.uint32(/* id 10, wireType 0 =*/80).bool(message.mapReportingEnabled);
                if (message.mapReportSettings != null && Object.hasOwnProperty.call(message, "mapReportSettings"))
                    $root.meshtastic.ModuleConfig.MapReportSettings.encode(message.mapReportSettings, writer.uint32(/* id 11, wireType 2 =*/90).fork(), q + 1).ldelim();
                return writer;
            };

            /**
             * Decodes a MQTTConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.MQTTConfig} MQTTConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            MQTTConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.MQTTConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.enabled = reader.bool();
                            break;
                        }
                    case 2: {
                            message.address = reader.string();
                            break;
                        }
                    case 3: {
                            message.username = reader.string();
                            break;
                        }
                    case 4: {
                            message.password = reader.string();
                            break;
                        }
                    case 5: {
                            message.encryptionEnabled = reader.bool();
                            break;
                        }
                    case 6: {
                            message.jsonEnabled = reader.bool();
                            break;
                        }
                    case 7: {
                            message.tlsEnabled = reader.bool();
                            break;
                        }
                    case 8: {
                            message.root = reader.string();
                            break;
                        }
                    case 9: {
                            message.proxyToClientEnabled = reader.bool();
                            break;
                        }
                    case 10: {
                            message.mapReportingEnabled = reader.bool();
                            break;
                        }
                    case 11: {
                            message.mapReportSettings = $root.meshtastic.ModuleConfig.MapReportSettings.decode(reader, reader.uint32(), undefined, long + 1);
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a MQTTConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            MQTTConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                if (message.address != null && Object.hasOwnProperty.call(message, "address"))
                    if (!$util.isString(message.address))
                        return "address: string expected";
                if (message.username != null && Object.hasOwnProperty.call(message, "username"))
                    if (!$util.isString(message.username))
                        return "username: string expected";
                if (message.password != null && Object.hasOwnProperty.call(message, "password"))
                    if (!$util.isString(message.password))
                        return "password: string expected";
                if (message.encryptionEnabled != null && Object.hasOwnProperty.call(message, "encryptionEnabled"))
                    if (typeof message.encryptionEnabled !== "boolean")
                        return "encryptionEnabled: boolean expected";
                if (message.jsonEnabled != null && Object.hasOwnProperty.call(message, "jsonEnabled"))
                    if (typeof message.jsonEnabled !== "boolean")
                        return "jsonEnabled: boolean expected";
                if (message.tlsEnabled != null && Object.hasOwnProperty.call(message, "tlsEnabled"))
                    if (typeof message.tlsEnabled !== "boolean")
                        return "tlsEnabled: boolean expected";
                if (message.root != null && Object.hasOwnProperty.call(message, "root"))
                    if (!$util.isString(message.root))
                        return "root: string expected";
                if (message.proxyToClientEnabled != null && Object.hasOwnProperty.call(message, "proxyToClientEnabled"))
                    if (typeof message.proxyToClientEnabled !== "boolean")
                        return "proxyToClientEnabled: boolean expected";
                if (message.mapReportingEnabled != null && Object.hasOwnProperty.call(message, "mapReportingEnabled"))
                    if (typeof message.mapReportingEnabled !== "boolean")
                        return "mapReportingEnabled: boolean expected";
                if (message.mapReportSettings != null && Object.hasOwnProperty.call(message, "mapReportSettings")) {
                    let error = $root.meshtastic.ModuleConfig.MapReportSettings.verify(message.mapReportSettings, long + 1);
                    if (error)
                        return "mapReportSettings." + error;
                }
                return null;
            };

            /**
             * Gets the default type url for MQTTConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.MQTTConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            MQTTConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.MQTTConfig";
            };

            return MQTTConfig;
        })();

        ModuleConfig.TelemetryConfig = (function() {

            /**
             * Properties of a TelemetryConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface ITelemetryConfig
             * @property {number|null} [deviceUpdateInterval] TelemetryConfig deviceUpdateInterval
             * @property {number|null} [environmentUpdateInterval] TelemetryConfig environmentUpdateInterval
             * @property {boolean|null} [environmentMeasurementEnabled] TelemetryConfig environmentMeasurementEnabled
             * @property {boolean|null} [environmentScreenEnabled] TelemetryConfig environmentScreenEnabled
             * @property {boolean|null} [environmentDisplayFahrenheit] TelemetryConfig environmentDisplayFahrenheit
             * @property {boolean|null} [airQualityEnabled] TelemetryConfig airQualityEnabled
             * @property {number|null} [airQualityInterval] TelemetryConfig airQualityInterval
             * @property {boolean|null} [powerMeasurementEnabled] TelemetryConfig powerMeasurementEnabled
             * @property {number|null} [powerUpdateInterval] TelemetryConfig powerUpdateInterval
             * @property {boolean|null} [powerScreenEnabled] TelemetryConfig powerScreenEnabled
             * @property {boolean|null} [deviceTelemetryEnabled] TelemetryConfig deviceTelemetryEnabled
             */

            /**
             * Constructs a new TelemetryConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a TelemetryConfig.
             * @implements ITelemetryConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.ITelemetryConfig=} [properties] Properties to set
             */
            function TelemetryConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * TelemetryConfig deviceUpdateInterval.
             * @member {number} deviceUpdateInterval
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @instance
             */
            TelemetryConfig.prototype.deviceUpdateInterval = 0;

            /**
             * TelemetryConfig environmentUpdateInterval.
             * @member {number} environmentUpdateInterval
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @instance
             */
            TelemetryConfig.prototype.environmentUpdateInterval = 0;

            /**
             * TelemetryConfig environmentMeasurementEnabled.
             * @member {boolean} environmentMeasurementEnabled
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @instance
             */
            TelemetryConfig.prototype.environmentMeasurementEnabled = false;

            /**
             * TelemetryConfig environmentScreenEnabled.
             * @member {boolean} environmentScreenEnabled
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @instance
             */
            TelemetryConfig.prototype.environmentScreenEnabled = false;

            /**
             * TelemetryConfig environmentDisplayFahrenheit.
             * @member {boolean} environmentDisplayFahrenheit
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @instance
             */
            TelemetryConfig.prototype.environmentDisplayFahrenheit = false;

            /**
             * TelemetryConfig airQualityEnabled.
             * @member {boolean} airQualityEnabled
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @instance
             */
            TelemetryConfig.prototype.airQualityEnabled = false;

            /**
             * TelemetryConfig airQualityInterval.
             * @member {number} airQualityInterval
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @instance
             */
            TelemetryConfig.prototype.airQualityInterval = 0;

            /**
             * TelemetryConfig powerMeasurementEnabled.
             * @member {boolean} powerMeasurementEnabled
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @instance
             */
            TelemetryConfig.prototype.powerMeasurementEnabled = false;

            /**
             * TelemetryConfig powerUpdateInterval.
             * @member {number} powerUpdateInterval
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @instance
             */
            TelemetryConfig.prototype.powerUpdateInterval = 0;

            /**
             * TelemetryConfig powerScreenEnabled.
             * @member {boolean} powerScreenEnabled
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @instance
             */
            TelemetryConfig.prototype.powerScreenEnabled = false;

            /**
             * TelemetryConfig deviceTelemetryEnabled.
             * @member {boolean} deviceTelemetryEnabled
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @instance
             */
            TelemetryConfig.prototype.deviceTelemetryEnabled = false;

            /**
             * Creates a new TelemetryConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @static
             * @param {meshtastic.ModuleConfig.ITelemetryConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.TelemetryConfig} TelemetryConfig instance
             */
            TelemetryConfig.create = function create(properties) {
                return new TelemetryConfig(properties);
            };

            /**
             * Encodes the specified TelemetryConfig message. Does not implicitly {@link meshtastic.ModuleConfig.TelemetryConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @static
             * @param {meshtastic.ModuleConfig.ITelemetryConfig} message TelemetryConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            TelemetryConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.deviceUpdateInterval != null && Object.hasOwnProperty.call(message, "deviceUpdateInterval"))
                    writer.uint32(/* id 1, wireType 0 =*/8).uint32(message.deviceUpdateInterval);
                if (message.environmentUpdateInterval != null && Object.hasOwnProperty.call(message, "environmentUpdateInterval"))
                    writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.environmentUpdateInterval);
                if (message.environmentMeasurementEnabled != null && Object.hasOwnProperty.call(message, "environmentMeasurementEnabled"))
                    writer.uint32(/* id 3, wireType 0 =*/24).bool(message.environmentMeasurementEnabled);
                if (message.environmentScreenEnabled != null && Object.hasOwnProperty.call(message, "environmentScreenEnabled"))
                    writer.uint32(/* id 4, wireType 0 =*/32).bool(message.environmentScreenEnabled);
                if (message.environmentDisplayFahrenheit != null && Object.hasOwnProperty.call(message, "environmentDisplayFahrenheit"))
                    writer.uint32(/* id 5, wireType 0 =*/40).bool(message.environmentDisplayFahrenheit);
                if (message.airQualityEnabled != null && Object.hasOwnProperty.call(message, "airQualityEnabled"))
                    writer.uint32(/* id 6, wireType 0 =*/48).bool(message.airQualityEnabled);
                if (message.airQualityInterval != null && Object.hasOwnProperty.call(message, "airQualityInterval"))
                    writer.uint32(/* id 7, wireType 0 =*/56).uint32(message.airQualityInterval);
                if (message.powerMeasurementEnabled != null && Object.hasOwnProperty.call(message, "powerMeasurementEnabled"))
                    writer.uint32(/* id 8, wireType 0 =*/64).bool(message.powerMeasurementEnabled);
                if (message.powerUpdateInterval != null && Object.hasOwnProperty.call(message, "powerUpdateInterval"))
                    writer.uint32(/* id 9, wireType 0 =*/72).uint32(message.powerUpdateInterval);
                if (message.powerScreenEnabled != null && Object.hasOwnProperty.call(message, "powerScreenEnabled"))
                    writer.uint32(/* id 10, wireType 0 =*/80).bool(message.powerScreenEnabled);
                if (message.deviceTelemetryEnabled != null && Object.hasOwnProperty.call(message, "deviceTelemetryEnabled"))
                    writer.uint32(/* id 14, wireType 0 =*/112).bool(message.deviceTelemetryEnabled);
                return writer;
            };

            /**
             * Decodes a TelemetryConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.TelemetryConfig} TelemetryConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            TelemetryConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.TelemetryConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.deviceUpdateInterval = reader.uint32();
                            break;
                        }
                    case 2: {
                            message.environmentUpdateInterval = reader.uint32();
                            break;
                        }
                    case 3: {
                            message.environmentMeasurementEnabled = reader.bool();
                            break;
                        }
                    case 4: {
                            message.environmentScreenEnabled = reader.bool();
                            break;
                        }
                    case 5: {
                            message.environmentDisplayFahrenheit = reader.bool();
                            break;
                        }
                    case 6: {
                            message.airQualityEnabled = reader.bool();
                            break;
                        }
                    case 7: {
                            message.airQualityInterval = reader.uint32();
                            break;
                        }
                    case 8: {
                            message.powerMeasurementEnabled = reader.bool();
                            break;
                        }
                    case 9: {
                            message.powerUpdateInterval = reader.uint32();
                            break;
                        }
                    case 10: {
                            message.powerScreenEnabled = reader.bool();
                            break;
                        }
                    case 14: {
                            message.deviceTelemetryEnabled = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a TelemetryConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            TelemetryConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.deviceUpdateInterval != null && Object.hasOwnProperty.call(message, "deviceUpdateInterval"))
                    if (!$util.isInteger(message.deviceUpdateInterval))
                        return "deviceUpdateInterval: integer expected";
                if (message.environmentUpdateInterval != null && Object.hasOwnProperty.call(message, "environmentUpdateInterval"))
                    if (!$util.isInteger(message.environmentUpdateInterval))
                        return "environmentUpdateInterval: integer expected";
                if (message.environmentMeasurementEnabled != null && Object.hasOwnProperty.call(message, "environmentMeasurementEnabled"))
                    if (typeof message.environmentMeasurementEnabled !== "boolean")
                        return "environmentMeasurementEnabled: boolean expected";
                if (message.environmentScreenEnabled != null && Object.hasOwnProperty.call(message, "environmentScreenEnabled"))
                    if (typeof message.environmentScreenEnabled !== "boolean")
                        return "environmentScreenEnabled: boolean expected";
                if (message.environmentDisplayFahrenheit != null && Object.hasOwnProperty.call(message, "environmentDisplayFahrenheit"))
                    if (typeof message.environmentDisplayFahrenheit !== "boolean")
                        return "environmentDisplayFahrenheit: boolean expected";
                if (message.airQualityEnabled != null && Object.hasOwnProperty.call(message, "airQualityEnabled"))
                    if (typeof message.airQualityEnabled !== "boolean")
                        return "airQualityEnabled: boolean expected";
                if (message.airQualityInterval != null && Object.hasOwnProperty.call(message, "airQualityInterval"))
                    if (!$util.isInteger(message.airQualityInterval))
                        return "airQualityInterval: integer expected";
                if (message.powerMeasurementEnabled != null && Object.hasOwnProperty.call(message, "powerMeasurementEnabled"))
                    if (typeof message.powerMeasurementEnabled !== "boolean")
                        return "powerMeasurementEnabled: boolean expected";
                if (message.powerUpdateInterval != null && Object.hasOwnProperty.call(message, "powerUpdateInterval"))
                    if (!$util.isInteger(message.powerUpdateInterval))
                        return "powerUpdateInterval: integer expected";
                if (message.powerScreenEnabled != null && Object.hasOwnProperty.call(message, "powerScreenEnabled"))
                    if (typeof message.powerScreenEnabled !== "boolean")
                        return "powerScreenEnabled: boolean expected";
                if (message.deviceTelemetryEnabled != null && Object.hasOwnProperty.call(message, "deviceTelemetryEnabled"))
                    if (typeof message.deviceTelemetryEnabled !== "boolean")
                        return "deviceTelemetryEnabled: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for TelemetryConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.TelemetryConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            TelemetryConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.TelemetryConfig";
            };

            return TelemetryConfig;
        })();

        ModuleConfig.SerialConfig = (function() {

            /**
             * Properties of a SerialConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface ISerialConfig
             * @property {boolean|null} [enabled] SerialConfig enabled
             * @property {boolean|null} [echo] SerialConfig echo
             * @property {number|null} [rxd] SerialConfig rxd
             * @property {number|null} [txd] SerialConfig txd
             * @property {number|null} [baud] SerialConfig baud
             * @property {number|null} [timeout] SerialConfig timeout
             * @property {number|null} [mode] SerialConfig mode
             */

            /**
             * Constructs a new SerialConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a SerialConfig.
             * @implements ISerialConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.ISerialConfig=} [properties] Properties to set
             */
            function SerialConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * SerialConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @instance
             */
            SerialConfig.prototype.enabled = false;

            /**
             * SerialConfig echo.
             * @member {boolean} echo
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @instance
             */
            SerialConfig.prototype.echo = false;

            /**
             * SerialConfig rxd.
             * @member {number} rxd
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @instance
             */
            SerialConfig.prototype.rxd = 0;

            /**
             * SerialConfig txd.
             * @member {number} txd
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @instance
             */
            SerialConfig.prototype.txd = 0;

            /**
             * SerialConfig baud.
             * @member {number} baud
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @instance
             */
            SerialConfig.prototype.baud = 0;

            /**
             * SerialConfig timeout.
             * @member {number} timeout
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @instance
             */
            SerialConfig.prototype.timeout = 0;

            /**
             * SerialConfig mode.
             * @member {number} mode
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @instance
             */
            SerialConfig.prototype.mode = 0;

            /**
             * Creates a new SerialConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @static
             * @param {meshtastic.ModuleConfig.ISerialConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.SerialConfig} SerialConfig instance
             */
            SerialConfig.create = function create(properties) {
                return new SerialConfig(properties);
            };

            /**
             * Encodes the specified SerialConfig message. Does not implicitly {@link meshtastic.ModuleConfig.SerialConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @static
             * @param {meshtastic.ModuleConfig.ISerialConfig} message SerialConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            SerialConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.enabled);
                if (message.echo != null && Object.hasOwnProperty.call(message, "echo"))
                    writer.uint32(/* id 2, wireType 0 =*/16).bool(message.echo);
                if (message.rxd != null && Object.hasOwnProperty.call(message, "rxd"))
                    writer.uint32(/* id 3, wireType 0 =*/24).uint32(message.rxd);
                if (message.txd != null && Object.hasOwnProperty.call(message, "txd"))
                    writer.uint32(/* id 4, wireType 0 =*/32).uint32(message.txd);
                if (message.baud != null && Object.hasOwnProperty.call(message, "baud"))
                    writer.uint32(/* id 5, wireType 0 =*/40).uint32(message.baud);
                if (message.timeout != null && Object.hasOwnProperty.call(message, "timeout"))
                    writer.uint32(/* id 6, wireType 0 =*/48).uint32(message.timeout);
                if (message.mode != null && Object.hasOwnProperty.call(message, "mode"))
                    writer.uint32(/* id 7, wireType 0 =*/56).uint32(message.mode);
                return writer;
            };

            /**
             * Decodes a SerialConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.SerialConfig} SerialConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            SerialConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.SerialConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.enabled = reader.bool();
                            break;
                        }
                    case 2: {
                            message.echo = reader.bool();
                            break;
                        }
                    case 3: {
                            message.rxd = reader.uint32();
                            break;
                        }
                    case 4: {
                            message.txd = reader.uint32();
                            break;
                        }
                    case 5: {
                            message.baud = reader.uint32();
                            break;
                        }
                    case 6: {
                            message.timeout = reader.uint32();
                            break;
                        }
                    case 7: {
                            message.mode = reader.uint32();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a SerialConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            SerialConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                if (message.echo != null && Object.hasOwnProperty.call(message, "echo"))
                    if (typeof message.echo !== "boolean")
                        return "echo: boolean expected";
                if (message.rxd != null && Object.hasOwnProperty.call(message, "rxd"))
                    if (!$util.isInteger(message.rxd))
                        return "rxd: integer expected";
                if (message.txd != null && Object.hasOwnProperty.call(message, "txd"))
                    if (!$util.isInteger(message.txd))
                        return "txd: integer expected";
                if (message.baud != null && Object.hasOwnProperty.call(message, "baud"))
                    if (!$util.isInteger(message.baud))
                        return "baud: integer expected";
                if (message.timeout != null && Object.hasOwnProperty.call(message, "timeout"))
                    if (!$util.isInteger(message.timeout))
                        return "timeout: integer expected";
                if (message.mode != null && Object.hasOwnProperty.call(message, "mode"))
                    if (!$util.isInteger(message.mode))
                        return "mode: integer expected";
                return null;
            };

            /**
             * Gets the default type url for SerialConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.SerialConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            SerialConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.SerialConfig";
            };

            return SerialConfig;
        })();

        ModuleConfig.ExternalNotificationConfig = (function() {

            /**
             * Properties of an ExternalNotificationConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface IExternalNotificationConfig
             * @property {boolean|null} [enabled] ExternalNotificationConfig enabled
             * @property {number|null} [outputMs] ExternalNotificationConfig outputMs
             * @property {number|null} [output] ExternalNotificationConfig output
             * @property {boolean|null} [active] ExternalNotificationConfig active
             * @property {boolean|null} [alertMessage] ExternalNotificationConfig alertMessage
             * @property {boolean|null} [alertBell] ExternalNotificationConfig alertBell
             * @property {boolean|null} [usePwm] ExternalNotificationConfig usePwm
             */

            /**
             * Constructs a new ExternalNotificationConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents an ExternalNotificationConfig.
             * @implements IExternalNotificationConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.IExternalNotificationConfig=} [properties] Properties to set
             */
            function ExternalNotificationConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * ExternalNotificationConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @instance
             */
            ExternalNotificationConfig.prototype.enabled = false;

            /**
             * ExternalNotificationConfig outputMs.
             * @member {number} outputMs
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @instance
             */
            ExternalNotificationConfig.prototype.outputMs = 0;

            /**
             * ExternalNotificationConfig output.
             * @member {number} output
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @instance
             */
            ExternalNotificationConfig.prototype.output = 0;

            /**
             * ExternalNotificationConfig active.
             * @member {boolean} active
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @instance
             */
            ExternalNotificationConfig.prototype.active = false;

            /**
             * ExternalNotificationConfig alertMessage.
             * @member {boolean} alertMessage
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @instance
             */
            ExternalNotificationConfig.prototype.alertMessage = false;

            /**
             * ExternalNotificationConfig alertBell.
             * @member {boolean} alertBell
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @instance
             */
            ExternalNotificationConfig.prototype.alertBell = false;

            /**
             * ExternalNotificationConfig usePwm.
             * @member {boolean} usePwm
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @instance
             */
            ExternalNotificationConfig.prototype.usePwm = false;

            /**
             * Creates a new ExternalNotificationConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @static
             * @param {meshtastic.ModuleConfig.IExternalNotificationConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.ExternalNotificationConfig} ExternalNotificationConfig instance
             */
            ExternalNotificationConfig.create = function create(properties) {
                return new ExternalNotificationConfig(properties);
            };

            /**
             * Encodes the specified ExternalNotificationConfig message. Does not implicitly {@link meshtastic.ModuleConfig.ExternalNotificationConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @static
             * @param {meshtastic.ModuleConfig.IExternalNotificationConfig} message ExternalNotificationConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            ExternalNotificationConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.enabled);
                if (message.outputMs != null && Object.hasOwnProperty.call(message, "outputMs"))
                    writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.outputMs);
                if (message.output != null && Object.hasOwnProperty.call(message, "output"))
                    writer.uint32(/* id 3, wireType 0 =*/24).uint32(message.output);
                if (message.active != null && Object.hasOwnProperty.call(message, "active"))
                    writer.uint32(/* id 4, wireType 0 =*/32).bool(message.active);
                if (message.alertMessage != null && Object.hasOwnProperty.call(message, "alertMessage"))
                    writer.uint32(/* id 5, wireType 0 =*/40).bool(message.alertMessage);
                if (message.alertBell != null && Object.hasOwnProperty.call(message, "alertBell"))
                    writer.uint32(/* id 6, wireType 0 =*/48).bool(message.alertBell);
                if (message.usePwm != null && Object.hasOwnProperty.call(message, "usePwm"))
                    writer.uint32(/* id 7, wireType 0 =*/56).bool(message.usePwm);
                return writer;
            };

            /**
             * Decodes an ExternalNotificationConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.ExternalNotificationConfig} ExternalNotificationConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            ExternalNotificationConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.ExternalNotificationConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.enabled = reader.bool();
                            break;
                        }
                    case 2: {
                            message.outputMs = reader.uint32();
                            break;
                        }
                    case 3: {
                            message.output = reader.uint32();
                            break;
                        }
                    case 4: {
                            message.active = reader.bool();
                            break;
                        }
                    case 5: {
                            message.alertMessage = reader.bool();
                            break;
                        }
                    case 6: {
                            message.alertBell = reader.bool();
                            break;
                        }
                    case 7: {
                            message.usePwm = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies an ExternalNotificationConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            ExternalNotificationConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                if (message.outputMs != null && Object.hasOwnProperty.call(message, "outputMs"))
                    if (!$util.isInteger(message.outputMs))
                        return "outputMs: integer expected";
                if (message.output != null && Object.hasOwnProperty.call(message, "output"))
                    if (!$util.isInteger(message.output))
                        return "output: integer expected";
                if (message.active != null && Object.hasOwnProperty.call(message, "active"))
                    if (typeof message.active !== "boolean")
                        return "active: boolean expected";
                if (message.alertMessage != null && Object.hasOwnProperty.call(message, "alertMessage"))
                    if (typeof message.alertMessage !== "boolean")
                        return "alertMessage: boolean expected";
                if (message.alertBell != null && Object.hasOwnProperty.call(message, "alertBell"))
                    if (typeof message.alertBell !== "boolean")
                        return "alertBell: boolean expected";
                if (message.usePwm != null && Object.hasOwnProperty.call(message, "usePwm"))
                    if (typeof message.usePwm !== "boolean")
                        return "usePwm: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for ExternalNotificationConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.ExternalNotificationConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            ExternalNotificationConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.ExternalNotificationConfig";
            };

            return ExternalNotificationConfig;
        })();

        ModuleConfig.StoreForwardConfig = (function() {

            /**
             * Properties of a StoreForwardConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface IStoreForwardConfig
             * @property {boolean|null} [enabled] StoreForwardConfig enabled
             * @property {boolean|null} [heartbeat] StoreForwardConfig heartbeat
             * @property {number|null} [records] StoreForwardConfig records
             * @property {number|null} [historyReturnMax] StoreForwardConfig historyReturnMax
             * @property {number|null} [historyReturnWindow] StoreForwardConfig historyReturnWindow
             * @property {boolean|null} [isServer] StoreForwardConfig isServer
             */

            /**
             * Constructs a new StoreForwardConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a StoreForwardConfig.
             * @implements IStoreForwardConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.IStoreForwardConfig=} [properties] Properties to set
             */
            function StoreForwardConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * StoreForwardConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.ModuleConfig.StoreForwardConfig
             * @instance
             */
            StoreForwardConfig.prototype.enabled = false;

            /**
             * StoreForwardConfig heartbeat.
             * @member {boolean} heartbeat
             * @memberof meshtastic.ModuleConfig.StoreForwardConfig
             * @instance
             */
            StoreForwardConfig.prototype.heartbeat = false;

            /**
             * StoreForwardConfig records.
             * @member {number} records
             * @memberof meshtastic.ModuleConfig.StoreForwardConfig
             * @instance
             */
            StoreForwardConfig.prototype.records = 0;

            /**
             * StoreForwardConfig historyReturnMax.
             * @member {number} historyReturnMax
             * @memberof meshtastic.ModuleConfig.StoreForwardConfig
             * @instance
             */
            StoreForwardConfig.prototype.historyReturnMax = 0;

            /**
             * StoreForwardConfig historyReturnWindow.
             * @member {number} historyReturnWindow
             * @memberof meshtastic.ModuleConfig.StoreForwardConfig
             * @instance
             */
            StoreForwardConfig.prototype.historyReturnWindow = 0;

            /**
             * StoreForwardConfig isServer.
             * @member {boolean} isServer
             * @memberof meshtastic.ModuleConfig.StoreForwardConfig
             * @instance
             */
            StoreForwardConfig.prototype.isServer = false;

            /**
             * Creates a new StoreForwardConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.StoreForwardConfig
             * @static
             * @param {meshtastic.ModuleConfig.IStoreForwardConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.StoreForwardConfig} StoreForwardConfig instance
             */
            StoreForwardConfig.create = function create(properties) {
                return new StoreForwardConfig(properties);
            };

            /**
             * Encodes the specified StoreForwardConfig message. Does not implicitly {@link meshtastic.ModuleConfig.StoreForwardConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.StoreForwardConfig
             * @static
             * @param {meshtastic.ModuleConfig.IStoreForwardConfig} message StoreForwardConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            StoreForwardConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.enabled);
                if (message.heartbeat != null && Object.hasOwnProperty.call(message, "heartbeat"))
                    writer.uint32(/* id 2, wireType 0 =*/16).bool(message.heartbeat);
                if (message.records != null && Object.hasOwnProperty.call(message, "records"))
                    writer.uint32(/* id 3, wireType 0 =*/24).uint32(message.records);
                if (message.historyReturnMax != null && Object.hasOwnProperty.call(message, "historyReturnMax"))
                    writer.uint32(/* id 4, wireType 0 =*/32).uint32(message.historyReturnMax);
                if (message.historyReturnWindow != null && Object.hasOwnProperty.call(message, "historyReturnWindow"))
                    writer.uint32(/* id 5, wireType 0 =*/40).uint32(message.historyReturnWindow);
                if (message.isServer != null && Object.hasOwnProperty.call(message, "isServer"))
                    writer.uint32(/* id 6, wireType 0 =*/48).bool(message.isServer);
                return writer;
            };

            /**
             * Decodes a StoreForwardConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.StoreForwardConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.StoreForwardConfig} StoreForwardConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            StoreForwardConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.StoreForwardConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.enabled = reader.bool();
                            break;
                        }
                    case 2: {
                            message.heartbeat = reader.bool();
                            break;
                        }
                    case 3: {
                            message.records = reader.uint32();
                            break;
                        }
                    case 4: {
                            message.historyReturnMax = reader.uint32();
                            break;
                        }
                    case 5: {
                            message.historyReturnWindow = reader.uint32();
                            break;
                        }
                    case 6: {
                            message.isServer = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a StoreForwardConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.StoreForwardConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            StoreForwardConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                if (message.heartbeat != null && Object.hasOwnProperty.call(message, "heartbeat"))
                    if (typeof message.heartbeat !== "boolean")
                        return "heartbeat: boolean expected";
                if (message.records != null && Object.hasOwnProperty.call(message, "records"))
                    if (!$util.isInteger(message.records))
                        return "records: integer expected";
                if (message.historyReturnMax != null && Object.hasOwnProperty.call(message, "historyReturnMax"))
                    if (!$util.isInteger(message.historyReturnMax))
                        return "historyReturnMax: integer expected";
                if (message.historyReturnWindow != null && Object.hasOwnProperty.call(message, "historyReturnWindow"))
                    if (!$util.isInteger(message.historyReturnWindow))
                        return "historyReturnWindow: integer expected";
                if (message.isServer != null && Object.hasOwnProperty.call(message, "isServer"))
                    if (typeof message.isServer !== "boolean")
                        return "isServer: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for StoreForwardConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.StoreForwardConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            StoreForwardConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.StoreForwardConfig";
            };

            return StoreForwardConfig;
        })();

        ModuleConfig.RangeTestConfig = (function() {

            /**
             * Properties of a RangeTestConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface IRangeTestConfig
             * @property {boolean|null} [enabled] RangeTestConfig enabled
             * @property {number|null} [sender] RangeTestConfig sender
             * @property {boolean|null} [save] RangeTestConfig save
             */

            /**
             * Constructs a new RangeTestConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a RangeTestConfig.
             * @implements IRangeTestConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.IRangeTestConfig=} [properties] Properties to set
             */
            function RangeTestConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * RangeTestConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.ModuleConfig.RangeTestConfig
             * @instance
             */
            RangeTestConfig.prototype.enabled = false;

            /**
             * RangeTestConfig sender.
             * @member {number} sender
             * @memberof meshtastic.ModuleConfig.RangeTestConfig
             * @instance
             */
            RangeTestConfig.prototype.sender = 0;

            /**
             * RangeTestConfig save.
             * @member {boolean} save
             * @memberof meshtastic.ModuleConfig.RangeTestConfig
             * @instance
             */
            RangeTestConfig.prototype.save = false;

            /**
             * Creates a new RangeTestConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.RangeTestConfig
             * @static
             * @param {meshtastic.ModuleConfig.IRangeTestConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.RangeTestConfig} RangeTestConfig instance
             */
            RangeTestConfig.create = function create(properties) {
                return new RangeTestConfig(properties);
            };

            /**
             * Encodes the specified RangeTestConfig message. Does not implicitly {@link meshtastic.ModuleConfig.RangeTestConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.RangeTestConfig
             * @static
             * @param {meshtastic.ModuleConfig.IRangeTestConfig} message RangeTestConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            RangeTestConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.enabled);
                if (message.sender != null && Object.hasOwnProperty.call(message, "sender"))
                    writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.sender);
                if (message.save != null && Object.hasOwnProperty.call(message, "save"))
                    writer.uint32(/* id 3, wireType 0 =*/24).bool(message.save);
                return writer;
            };

            /**
             * Decodes a RangeTestConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.RangeTestConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.RangeTestConfig} RangeTestConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            RangeTestConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.RangeTestConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.enabled = reader.bool();
                            break;
                        }
                    case 2: {
                            message.sender = reader.uint32();
                            break;
                        }
                    case 3: {
                            message.save = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a RangeTestConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.RangeTestConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            RangeTestConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                if (message.sender != null && Object.hasOwnProperty.call(message, "sender"))
                    if (!$util.isInteger(message.sender))
                        return "sender: integer expected";
                if (message.save != null && Object.hasOwnProperty.call(message, "save"))
                    if (typeof message.save !== "boolean")
                        return "save: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for RangeTestConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.RangeTestConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            RangeTestConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.RangeTestConfig";
            };

            return RangeTestConfig;
        })();

        ModuleConfig.CannedMessageConfig = (function() {

            /**
             * Properties of a CannedMessageConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface ICannedMessageConfig
             * @property {boolean|null} [rotary1Enabled] CannedMessageConfig rotary1Enabled
             * @property {boolean|null} [enabled] CannedMessageConfig enabled
             * @property {boolean|null} [sendBell] CannedMessageConfig sendBell
             */

            /**
             * Constructs a new CannedMessageConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a CannedMessageConfig.
             * @implements ICannedMessageConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.ICannedMessageConfig=} [properties] Properties to set
             */
            function CannedMessageConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * CannedMessageConfig rotary1Enabled.
             * @member {boolean} rotary1Enabled
             * @memberof meshtastic.ModuleConfig.CannedMessageConfig
             * @instance
             */
            CannedMessageConfig.prototype.rotary1Enabled = false;

            /**
             * CannedMessageConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.ModuleConfig.CannedMessageConfig
             * @instance
             */
            CannedMessageConfig.prototype.enabled = false;

            /**
             * CannedMessageConfig sendBell.
             * @member {boolean} sendBell
             * @memberof meshtastic.ModuleConfig.CannedMessageConfig
             * @instance
             */
            CannedMessageConfig.prototype.sendBell = false;

            /**
             * Creates a new CannedMessageConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.CannedMessageConfig
             * @static
             * @param {meshtastic.ModuleConfig.ICannedMessageConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.CannedMessageConfig} CannedMessageConfig instance
             */
            CannedMessageConfig.create = function create(properties) {
                return new CannedMessageConfig(properties);
            };

            /**
             * Encodes the specified CannedMessageConfig message. Does not implicitly {@link meshtastic.ModuleConfig.CannedMessageConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.CannedMessageConfig
             * @static
             * @param {meshtastic.ModuleConfig.ICannedMessageConfig} message CannedMessageConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            CannedMessageConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.rotary1Enabled != null && Object.hasOwnProperty.call(message, "rotary1Enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.rotary1Enabled);
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 9, wireType 0 =*/72).bool(message.enabled);
                if (message.sendBell != null && Object.hasOwnProperty.call(message, "sendBell"))
                    writer.uint32(/* id 11, wireType 0 =*/88).bool(message.sendBell);
                return writer;
            };

            /**
             * Decodes a CannedMessageConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.CannedMessageConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.CannedMessageConfig} CannedMessageConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            CannedMessageConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.CannedMessageConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.rotary1Enabled = reader.bool();
                            break;
                        }
                    case 9: {
                            message.enabled = reader.bool();
                            break;
                        }
                    case 11: {
                            message.sendBell = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a CannedMessageConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.CannedMessageConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            CannedMessageConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.rotary1Enabled != null && Object.hasOwnProperty.call(message, "rotary1Enabled"))
                    if (typeof message.rotary1Enabled !== "boolean")
                        return "rotary1Enabled: boolean expected";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                if (message.sendBell != null && Object.hasOwnProperty.call(message, "sendBell"))
                    if (typeof message.sendBell !== "boolean")
                        return "sendBell: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for CannedMessageConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.CannedMessageConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            CannedMessageConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.CannedMessageConfig";
            };

            return CannedMessageConfig;
        })();

        ModuleConfig.AudioConfig = (function() {

            /**
             * Properties of an AudioConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface IAudioConfig
             * @property {boolean|null} [codec2Enabled] AudioConfig codec2Enabled
             */

            /**
             * Constructs a new AudioConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents an AudioConfig.
             * @implements IAudioConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.IAudioConfig=} [properties] Properties to set
             */
            function AudioConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * AudioConfig codec2Enabled.
             * @member {boolean} codec2Enabled
             * @memberof meshtastic.ModuleConfig.AudioConfig
             * @instance
             */
            AudioConfig.prototype.codec2Enabled = false;

            /**
             * Creates a new AudioConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.AudioConfig
             * @static
             * @param {meshtastic.ModuleConfig.IAudioConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.AudioConfig} AudioConfig instance
             */
            AudioConfig.create = function create(properties) {
                return new AudioConfig(properties);
            };

            /**
             * Encodes the specified AudioConfig message. Does not implicitly {@link meshtastic.ModuleConfig.AudioConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.AudioConfig
             * @static
             * @param {meshtastic.ModuleConfig.IAudioConfig} message AudioConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            AudioConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.codec2Enabled != null && Object.hasOwnProperty.call(message, "codec2Enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.codec2Enabled);
                return writer;
            };

            /**
             * Decodes an AudioConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.AudioConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.AudioConfig} AudioConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            AudioConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.AudioConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.codec2Enabled = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies an AudioConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.AudioConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            AudioConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.codec2Enabled != null && Object.hasOwnProperty.call(message, "codec2Enabled"))
                    if (typeof message.codec2Enabled !== "boolean")
                        return "codec2Enabled: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for AudioConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.AudioConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            AudioConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.AudioConfig";
            };

            return AudioConfig;
        })();

        ModuleConfig.RemoteHardwareConfig = (function() {

            /**
             * Properties of a RemoteHardwareConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface IRemoteHardwareConfig
             * @property {boolean|null} [enabled] RemoteHardwareConfig enabled
             * @property {boolean|null} [allowUndefinedPinAccess] RemoteHardwareConfig allowUndefinedPinAccess
             */

            /**
             * Constructs a new RemoteHardwareConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a RemoteHardwareConfig.
             * @implements IRemoteHardwareConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.IRemoteHardwareConfig=} [properties] Properties to set
             */
            function RemoteHardwareConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * RemoteHardwareConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.ModuleConfig.RemoteHardwareConfig
             * @instance
             */
            RemoteHardwareConfig.prototype.enabled = false;

            /**
             * RemoteHardwareConfig allowUndefinedPinAccess.
             * @member {boolean} allowUndefinedPinAccess
             * @memberof meshtastic.ModuleConfig.RemoteHardwareConfig
             * @instance
             */
            RemoteHardwareConfig.prototype.allowUndefinedPinAccess = false;

            /**
             * Creates a new RemoteHardwareConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.RemoteHardwareConfig
             * @static
             * @param {meshtastic.ModuleConfig.IRemoteHardwareConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.RemoteHardwareConfig} RemoteHardwareConfig instance
             */
            RemoteHardwareConfig.create = function create(properties) {
                return new RemoteHardwareConfig(properties);
            };

            /**
             * Encodes the specified RemoteHardwareConfig message. Does not implicitly {@link meshtastic.ModuleConfig.RemoteHardwareConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.RemoteHardwareConfig
             * @static
             * @param {meshtastic.ModuleConfig.IRemoteHardwareConfig} message RemoteHardwareConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            RemoteHardwareConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.enabled);
                if (message.allowUndefinedPinAccess != null && Object.hasOwnProperty.call(message, "allowUndefinedPinAccess"))
                    writer.uint32(/* id 2, wireType 0 =*/16).bool(message.allowUndefinedPinAccess);
                return writer;
            };

            /**
             * Decodes a RemoteHardwareConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.RemoteHardwareConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.RemoteHardwareConfig} RemoteHardwareConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            RemoteHardwareConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.RemoteHardwareConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.enabled = reader.bool();
                            break;
                        }
                    case 2: {
                            message.allowUndefinedPinAccess = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a RemoteHardwareConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.RemoteHardwareConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            RemoteHardwareConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                if (message.allowUndefinedPinAccess != null && Object.hasOwnProperty.call(message, "allowUndefinedPinAccess"))
                    if (typeof message.allowUndefinedPinAccess !== "boolean")
                        return "allowUndefinedPinAccess: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for RemoteHardwareConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.RemoteHardwareConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            RemoteHardwareConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.RemoteHardwareConfig";
            };

            return RemoteHardwareConfig;
        })();

        ModuleConfig.NeighborInfoConfig = (function() {

            /**
             * Properties of a NeighborInfoConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface INeighborInfoConfig
             * @property {boolean|null} [enabled] NeighborInfoConfig enabled
             * @property {number|null} [updateInterval] NeighborInfoConfig updateInterval
             * @property {boolean|null} [transmitOverLora] NeighborInfoConfig transmitOverLora
             */

            /**
             * Constructs a new NeighborInfoConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a NeighborInfoConfig.
             * @implements INeighborInfoConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.INeighborInfoConfig=} [properties] Properties to set
             */
            function NeighborInfoConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * NeighborInfoConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.ModuleConfig.NeighborInfoConfig
             * @instance
             */
            NeighborInfoConfig.prototype.enabled = false;

            /**
             * NeighborInfoConfig updateInterval.
             * @member {number} updateInterval
             * @memberof meshtastic.ModuleConfig.NeighborInfoConfig
             * @instance
             */
            NeighborInfoConfig.prototype.updateInterval = 0;

            /**
             * NeighborInfoConfig transmitOverLora.
             * @member {boolean} transmitOverLora
             * @memberof meshtastic.ModuleConfig.NeighborInfoConfig
             * @instance
             */
            NeighborInfoConfig.prototype.transmitOverLora = false;

            /**
             * Creates a new NeighborInfoConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.NeighborInfoConfig
             * @static
             * @param {meshtastic.ModuleConfig.INeighborInfoConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.NeighborInfoConfig} NeighborInfoConfig instance
             */
            NeighborInfoConfig.create = function create(properties) {
                return new NeighborInfoConfig(properties);
            };

            /**
             * Encodes the specified NeighborInfoConfig message. Does not implicitly {@link meshtastic.ModuleConfig.NeighborInfoConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.NeighborInfoConfig
             * @static
             * @param {meshtastic.ModuleConfig.INeighborInfoConfig} message NeighborInfoConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            NeighborInfoConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.enabled);
                if (message.updateInterval != null && Object.hasOwnProperty.call(message, "updateInterval"))
                    writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.updateInterval);
                if (message.transmitOverLora != null && Object.hasOwnProperty.call(message, "transmitOverLora"))
                    writer.uint32(/* id 3, wireType 0 =*/24).bool(message.transmitOverLora);
                return writer;
            };

            /**
             * Decodes a NeighborInfoConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.NeighborInfoConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.NeighborInfoConfig} NeighborInfoConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            NeighborInfoConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.NeighborInfoConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.enabled = reader.bool();
                            break;
                        }
                    case 2: {
                            message.updateInterval = reader.uint32();
                            break;
                        }
                    case 3: {
                            message.transmitOverLora = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a NeighborInfoConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.NeighborInfoConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            NeighborInfoConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                if (message.updateInterval != null && Object.hasOwnProperty.call(message, "updateInterval"))
                    if (!$util.isInteger(message.updateInterval))
                        return "updateInterval: integer expected";
                if (message.transmitOverLora != null && Object.hasOwnProperty.call(message, "transmitOverLora"))
                    if (typeof message.transmitOverLora !== "boolean")
                        return "transmitOverLora: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for NeighborInfoConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.NeighborInfoConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            NeighborInfoConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.NeighborInfoConfig";
            };

            return NeighborInfoConfig;
        })();

        ModuleConfig.AmbientLightingConfig = (function() {

            /**
             * Properties of an AmbientLightingConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface IAmbientLightingConfig
             * @property {boolean|null} [ledState] AmbientLightingConfig ledState
             * @property {number|null} [current] AmbientLightingConfig current
             * @property {number|null} [red] AmbientLightingConfig red
             * @property {number|null} [green] AmbientLightingConfig green
             * @property {number|null} [blue] AmbientLightingConfig blue
             */

            /**
             * Constructs a new AmbientLightingConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents an AmbientLightingConfig.
             * @implements IAmbientLightingConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.IAmbientLightingConfig=} [properties] Properties to set
             */
            function AmbientLightingConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * AmbientLightingConfig ledState.
             * @member {boolean} ledState
             * @memberof meshtastic.ModuleConfig.AmbientLightingConfig
             * @instance
             */
            AmbientLightingConfig.prototype.ledState = false;

            /**
             * AmbientLightingConfig current.
             * @member {number} current
             * @memberof meshtastic.ModuleConfig.AmbientLightingConfig
             * @instance
             */
            AmbientLightingConfig.prototype.current = 0;

            /**
             * AmbientLightingConfig red.
             * @member {number} red
             * @memberof meshtastic.ModuleConfig.AmbientLightingConfig
             * @instance
             */
            AmbientLightingConfig.prototype.red = 0;

            /**
             * AmbientLightingConfig green.
             * @member {number} green
             * @memberof meshtastic.ModuleConfig.AmbientLightingConfig
             * @instance
             */
            AmbientLightingConfig.prototype.green = 0;

            /**
             * AmbientLightingConfig blue.
             * @member {number} blue
             * @memberof meshtastic.ModuleConfig.AmbientLightingConfig
             * @instance
             */
            AmbientLightingConfig.prototype.blue = 0;

            /**
             * Creates a new AmbientLightingConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.AmbientLightingConfig
             * @static
             * @param {meshtastic.ModuleConfig.IAmbientLightingConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.AmbientLightingConfig} AmbientLightingConfig instance
             */
            AmbientLightingConfig.create = function create(properties) {
                return new AmbientLightingConfig(properties);
            };

            /**
             * Encodes the specified AmbientLightingConfig message. Does not implicitly {@link meshtastic.ModuleConfig.AmbientLightingConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.AmbientLightingConfig
             * @static
             * @param {meshtastic.ModuleConfig.IAmbientLightingConfig} message AmbientLightingConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            AmbientLightingConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.ledState != null && Object.hasOwnProperty.call(message, "ledState"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.ledState);
                if (message.current != null && Object.hasOwnProperty.call(message, "current"))
                    writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.current);
                if (message.red != null && Object.hasOwnProperty.call(message, "red"))
                    writer.uint32(/* id 3, wireType 0 =*/24).uint32(message.red);
                if (message.green != null && Object.hasOwnProperty.call(message, "green"))
                    writer.uint32(/* id 4, wireType 0 =*/32).uint32(message.green);
                if (message.blue != null && Object.hasOwnProperty.call(message, "blue"))
                    writer.uint32(/* id 5, wireType 0 =*/40).uint32(message.blue);
                return writer;
            };

            /**
             * Decodes an AmbientLightingConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.AmbientLightingConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.AmbientLightingConfig} AmbientLightingConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            AmbientLightingConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.AmbientLightingConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.ledState = reader.bool();
                            break;
                        }
                    case 2: {
                            message.current = reader.uint32();
                            break;
                        }
                    case 3: {
                            message.red = reader.uint32();
                            break;
                        }
                    case 4: {
                            message.green = reader.uint32();
                            break;
                        }
                    case 5: {
                            message.blue = reader.uint32();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies an AmbientLightingConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.AmbientLightingConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            AmbientLightingConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.ledState != null && Object.hasOwnProperty.call(message, "ledState"))
                    if (typeof message.ledState !== "boolean")
                        return "ledState: boolean expected";
                if (message.current != null && Object.hasOwnProperty.call(message, "current"))
                    if (!$util.isInteger(message.current))
                        return "current: integer expected";
                if (message.red != null && Object.hasOwnProperty.call(message, "red"))
                    if (!$util.isInteger(message.red))
                        return "red: integer expected";
                if (message.green != null && Object.hasOwnProperty.call(message, "green"))
                    if (!$util.isInteger(message.green))
                        return "green: integer expected";
                if (message.blue != null && Object.hasOwnProperty.call(message, "blue"))
                    if (!$util.isInteger(message.blue))
                        return "blue: integer expected";
                return null;
            };

            /**
             * Gets the default type url for AmbientLightingConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.AmbientLightingConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            AmbientLightingConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.AmbientLightingConfig";
            };

            return AmbientLightingConfig;
        })();

        ModuleConfig.DetectionSensorConfig = (function() {

            /**
             * Properties of a DetectionSensorConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface IDetectionSensorConfig
             * @property {boolean|null} [enabled] DetectionSensorConfig enabled
             * @property {number|null} [minimumBroadcastSecs] DetectionSensorConfig minimumBroadcastSecs
             * @property {number|null} [stateBroadcastSecs] DetectionSensorConfig stateBroadcastSecs
             * @property {boolean|null} [sendBell] DetectionSensorConfig sendBell
             * @property {string|null} [name] DetectionSensorConfig name
             * @property {number|null} [monitorPin] DetectionSensorConfig monitorPin
             */

            /**
             * Constructs a new DetectionSensorConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a DetectionSensorConfig.
             * @implements IDetectionSensorConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.IDetectionSensorConfig=} [properties] Properties to set
             */
            function DetectionSensorConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * DetectionSensorConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.ModuleConfig.DetectionSensorConfig
             * @instance
             */
            DetectionSensorConfig.prototype.enabled = false;

            /**
             * DetectionSensorConfig minimumBroadcastSecs.
             * @member {number} minimumBroadcastSecs
             * @memberof meshtastic.ModuleConfig.DetectionSensorConfig
             * @instance
             */
            DetectionSensorConfig.prototype.minimumBroadcastSecs = 0;

            /**
             * DetectionSensorConfig stateBroadcastSecs.
             * @member {number} stateBroadcastSecs
             * @memberof meshtastic.ModuleConfig.DetectionSensorConfig
             * @instance
             */
            DetectionSensorConfig.prototype.stateBroadcastSecs = 0;

            /**
             * DetectionSensorConfig sendBell.
             * @member {boolean} sendBell
             * @memberof meshtastic.ModuleConfig.DetectionSensorConfig
             * @instance
             */
            DetectionSensorConfig.prototype.sendBell = false;

            /**
             * DetectionSensorConfig name.
             * @member {string} name
             * @memberof meshtastic.ModuleConfig.DetectionSensorConfig
             * @instance
             */
            DetectionSensorConfig.prototype.name = "";

            /**
             * DetectionSensorConfig monitorPin.
             * @member {number} monitorPin
             * @memberof meshtastic.ModuleConfig.DetectionSensorConfig
             * @instance
             */
            DetectionSensorConfig.prototype.monitorPin = 0;

            /**
             * Creates a new DetectionSensorConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.DetectionSensorConfig
             * @static
             * @param {meshtastic.ModuleConfig.IDetectionSensorConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.DetectionSensorConfig} DetectionSensorConfig instance
             */
            DetectionSensorConfig.create = function create(properties) {
                return new DetectionSensorConfig(properties);
            };

            /**
             * Encodes the specified DetectionSensorConfig message. Does not implicitly {@link meshtastic.ModuleConfig.DetectionSensorConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.DetectionSensorConfig
             * @static
             * @param {meshtastic.ModuleConfig.IDetectionSensorConfig} message DetectionSensorConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            DetectionSensorConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.enabled);
                if (message.minimumBroadcastSecs != null && Object.hasOwnProperty.call(message, "minimumBroadcastSecs"))
                    writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.minimumBroadcastSecs);
                if (message.stateBroadcastSecs != null && Object.hasOwnProperty.call(message, "stateBroadcastSecs"))
                    writer.uint32(/* id 3, wireType 0 =*/24).uint32(message.stateBroadcastSecs);
                if (message.sendBell != null && Object.hasOwnProperty.call(message, "sendBell"))
                    writer.uint32(/* id 4, wireType 0 =*/32).bool(message.sendBell);
                if (message.name != null && Object.hasOwnProperty.call(message, "name"))
                    writer.uint32(/* id 5, wireType 2 =*/42).string(message.name);
                if (message.monitorPin != null && Object.hasOwnProperty.call(message, "monitorPin"))
                    writer.uint32(/* id 6, wireType 0 =*/48).uint32(message.monitorPin);
                return writer;
            };

            /**
             * Decodes a DetectionSensorConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.DetectionSensorConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.DetectionSensorConfig} DetectionSensorConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            DetectionSensorConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.DetectionSensorConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.enabled = reader.bool();
                            break;
                        }
                    case 2: {
                            message.minimumBroadcastSecs = reader.uint32();
                            break;
                        }
                    case 3: {
                            message.stateBroadcastSecs = reader.uint32();
                            break;
                        }
                    case 4: {
                            message.sendBell = reader.bool();
                            break;
                        }
                    case 5: {
                            message.name = reader.string();
                            break;
                        }
                    case 6: {
                            message.monitorPin = reader.uint32();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a DetectionSensorConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.DetectionSensorConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            DetectionSensorConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                if (message.minimumBroadcastSecs != null && Object.hasOwnProperty.call(message, "minimumBroadcastSecs"))
                    if (!$util.isInteger(message.minimumBroadcastSecs))
                        return "minimumBroadcastSecs: integer expected";
                if (message.stateBroadcastSecs != null && Object.hasOwnProperty.call(message, "stateBroadcastSecs"))
                    if (!$util.isInteger(message.stateBroadcastSecs))
                        return "stateBroadcastSecs: integer expected";
                if (message.sendBell != null && Object.hasOwnProperty.call(message, "sendBell"))
                    if (typeof message.sendBell !== "boolean")
                        return "sendBell: boolean expected";
                if (message.name != null && Object.hasOwnProperty.call(message, "name"))
                    if (!$util.isString(message.name))
                        return "name: string expected";
                if (message.monitorPin != null && Object.hasOwnProperty.call(message, "monitorPin"))
                    if (!$util.isInteger(message.monitorPin))
                        return "monitorPin: integer expected";
                return null;
            };

            /**
             * Gets the default type url for DetectionSensorConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.DetectionSensorConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            DetectionSensorConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.DetectionSensorConfig";
            };

            return DetectionSensorConfig;
        })();

        ModuleConfig.PaxcounterConfig = (function() {

            /**
             * Properties of a PaxcounterConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface IPaxcounterConfig
             * @property {boolean|null} [enabled] PaxcounterConfig enabled
             * @property {number|null} [paxcounterUpdateInterval] PaxcounterConfig paxcounterUpdateInterval
             */

            /**
             * Constructs a new PaxcounterConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a PaxcounterConfig.
             * @implements IPaxcounterConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.IPaxcounterConfig=} [properties] Properties to set
             */
            function PaxcounterConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * PaxcounterConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.ModuleConfig.PaxcounterConfig
             * @instance
             */
            PaxcounterConfig.prototype.enabled = false;

            /**
             * PaxcounterConfig paxcounterUpdateInterval.
             * @member {number} paxcounterUpdateInterval
             * @memberof meshtastic.ModuleConfig.PaxcounterConfig
             * @instance
             */
            PaxcounterConfig.prototype.paxcounterUpdateInterval = 0;

            /**
             * Creates a new PaxcounterConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.PaxcounterConfig
             * @static
             * @param {meshtastic.ModuleConfig.IPaxcounterConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.PaxcounterConfig} PaxcounterConfig instance
             */
            PaxcounterConfig.create = function create(properties) {
                return new PaxcounterConfig(properties);
            };

            /**
             * Encodes the specified PaxcounterConfig message. Does not implicitly {@link meshtastic.ModuleConfig.PaxcounterConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.PaxcounterConfig
             * @static
             * @param {meshtastic.ModuleConfig.IPaxcounterConfig} message PaxcounterConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            PaxcounterConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.enabled);
                if (message.paxcounterUpdateInterval != null && Object.hasOwnProperty.call(message, "paxcounterUpdateInterval"))
                    writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.paxcounterUpdateInterval);
                return writer;
            };

            /**
             * Decodes a PaxcounterConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.PaxcounterConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.PaxcounterConfig} PaxcounterConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            PaxcounterConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.PaxcounterConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.enabled = reader.bool();
                            break;
                        }
                    case 2: {
                            message.paxcounterUpdateInterval = reader.uint32();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a PaxcounterConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.PaxcounterConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            PaxcounterConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                if (message.paxcounterUpdateInterval != null && Object.hasOwnProperty.call(message, "paxcounterUpdateInterval"))
                    if (!$util.isInteger(message.paxcounterUpdateInterval))
                        return "paxcounterUpdateInterval: integer expected";
                return null;
            };

            /**
             * Gets the default type url for PaxcounterConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.PaxcounterConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            PaxcounterConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.PaxcounterConfig";
            };

            return PaxcounterConfig;
        })();

        ModuleConfig.StatusMessageConfig = (function() {

            /**
             * Properties of a StatusMessageConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface IStatusMessageConfig
             * @property {string|null} [nodeStatus] StatusMessageConfig nodeStatus
             */

            /**
             * Constructs a new StatusMessageConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a StatusMessageConfig.
             * @implements IStatusMessageConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.IStatusMessageConfig=} [properties] Properties to set
             */
            function StatusMessageConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * StatusMessageConfig nodeStatus.
             * @member {string} nodeStatus
             * @memberof meshtastic.ModuleConfig.StatusMessageConfig
             * @instance
             */
            StatusMessageConfig.prototype.nodeStatus = "";

            /**
             * Creates a new StatusMessageConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.StatusMessageConfig
             * @static
             * @param {meshtastic.ModuleConfig.IStatusMessageConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.StatusMessageConfig} StatusMessageConfig instance
             */
            StatusMessageConfig.create = function create(properties) {
                return new StatusMessageConfig(properties);
            };

            /**
             * Encodes the specified StatusMessageConfig message. Does not implicitly {@link meshtastic.ModuleConfig.StatusMessageConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.StatusMessageConfig
             * @static
             * @param {meshtastic.ModuleConfig.IStatusMessageConfig} message StatusMessageConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            StatusMessageConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.nodeStatus != null && Object.hasOwnProperty.call(message, "nodeStatus"))
                    writer.uint32(/* id 1, wireType 2 =*/10).string(message.nodeStatus);
                return writer;
            };

            /**
             * Decodes a StatusMessageConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.StatusMessageConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.StatusMessageConfig} StatusMessageConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            StatusMessageConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.StatusMessageConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.nodeStatus = reader.string();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a StatusMessageConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.StatusMessageConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            StatusMessageConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.nodeStatus != null && Object.hasOwnProperty.call(message, "nodeStatus"))
                    if (!$util.isString(message.nodeStatus))
                        return "nodeStatus: string expected";
                return null;
            };

            /**
             * Gets the default type url for StatusMessageConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.StatusMessageConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            StatusMessageConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.StatusMessageConfig";
            };

            return StatusMessageConfig;
        })();

        ModuleConfig.TrafficManagementConfig = (function() {

            /**
             * Properties of a TrafficManagementConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface ITrafficManagementConfig
             * @property {boolean|null} [enabled] TrafficManagementConfig enabled
             */

            /**
             * Constructs a new TrafficManagementConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a TrafficManagementConfig.
             * @implements ITrafficManagementConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.ITrafficManagementConfig=} [properties] Properties to set
             */
            function TrafficManagementConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * TrafficManagementConfig enabled.
             * @member {boolean} enabled
             * @memberof meshtastic.ModuleConfig.TrafficManagementConfig
             * @instance
             */
            TrafficManagementConfig.prototype.enabled = false;

            /**
             * Creates a new TrafficManagementConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.TrafficManagementConfig
             * @static
             * @param {meshtastic.ModuleConfig.ITrafficManagementConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.TrafficManagementConfig} TrafficManagementConfig instance
             */
            TrafficManagementConfig.create = function create(properties) {
                return new TrafficManagementConfig(properties);
            };

            /**
             * Encodes the specified TrafficManagementConfig message. Does not implicitly {@link meshtastic.ModuleConfig.TrafficManagementConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.TrafficManagementConfig
             * @static
             * @param {meshtastic.ModuleConfig.ITrafficManagementConfig} message TrafficManagementConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            TrafficManagementConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    writer.uint32(/* id 1, wireType 0 =*/8).bool(message.enabled);
                return writer;
            };

            /**
             * Decodes a TrafficManagementConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.TrafficManagementConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.TrafficManagementConfig} TrafficManagementConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            TrafficManagementConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.TrafficManagementConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.enabled = reader.bool();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a TrafficManagementConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.TrafficManagementConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            TrafficManagementConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.enabled != null && Object.hasOwnProperty.call(message, "enabled"))
                    if (typeof message.enabled !== "boolean")
                        return "enabled: boolean expected";
                return null;
            };

            /**
             * Gets the default type url for TrafficManagementConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.TrafficManagementConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            TrafficManagementConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.TrafficManagementConfig";
            };

            return TrafficManagementConfig;
        })();

        ModuleConfig.TAKConfig = (function() {

            /**
             * Properties of a TAKConfig.
             * @memberof meshtastic.ModuleConfig
             * @interface ITAKConfig
             * @property {number|null} [team] TAKConfig team
             * @property {number|null} [role] TAKConfig role
             */

            /**
             * Constructs a new TAKConfig.
             * @memberof meshtastic.ModuleConfig
             * @classdesc Represents a TAKConfig.
             * @implements ITAKConfig
             * @constructor
             * @param {meshtastic.ModuleConfig.ITAKConfig=} [properties] Properties to set
             */
            function TAKConfig(properties) {
                if (properties)
                    for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                        if (properties[keys[i]] != null && keys[i] !== "__proto__")
                            this[keys[i]] = properties[keys[i]];
            }

            /**
             * TAKConfig team.
             * @member {number} team
             * @memberof meshtastic.ModuleConfig.TAKConfig
             * @instance
             */
            TAKConfig.prototype.team = 0;

            /**
             * TAKConfig role.
             * @member {number} role
             * @memberof meshtastic.ModuleConfig.TAKConfig
             * @instance
             */
            TAKConfig.prototype.role = 0;

            /**
             * Creates a new TAKConfig instance using the specified properties.
             * @function create
             * @memberof meshtastic.ModuleConfig.TAKConfig
             * @static
             * @param {meshtastic.ModuleConfig.ITAKConfig=} [properties] Properties to set
             * @returns {meshtastic.ModuleConfig.TAKConfig} TAKConfig instance
             */
            TAKConfig.create = function create(properties) {
                return new TAKConfig(properties);
            };

            /**
             * Encodes the specified TAKConfig message. Does not implicitly {@link meshtastic.ModuleConfig.TAKConfig.verify|verify} messages.
             * @function encode
             * @memberof meshtastic.ModuleConfig.TAKConfig
             * @static
             * @param {meshtastic.ModuleConfig.ITAKConfig} message TAKConfig message or plain object to encode
             * @param {$protobuf.Writer} [writer] Writer to encode to
             * @returns {$protobuf.Writer} Writer
             */
            TAKConfig.encode = function encode(message, writer, q) {
                if (!writer)
                    writer = $Writer.create();
                if (q === undefined)
                    q = 0;
                if (q > $util.recursionLimit)
                    throw Error("max depth exceeded");
                if (message.team != null && Object.hasOwnProperty.call(message, "team"))
                    writer.uint32(/* id 1, wireType 0 =*/8).uint32(message.team);
                if (message.role != null && Object.hasOwnProperty.call(message, "role"))
                    writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.role);
                return writer;
            };

            /**
             * Decodes a TAKConfig message from the specified reader or buffer.
             * @function decode
             * @memberof meshtastic.ModuleConfig.TAKConfig
             * @static
             * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
             * @param {number} [length] Message length if known beforehand
             * @returns {meshtastic.ModuleConfig.TAKConfig} TAKConfig
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            TAKConfig.decode = function decode(reader, length, error, long) {
                if (!(reader instanceof $Reader))
                    reader = $Reader.create(reader);
                if (long === undefined)
                    long = 0;
                if (long > $Reader.recursionLimit)
                    throw Error("maximum nesting depth exceeded");
                let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ModuleConfig.TAKConfig();
                while (reader.pos < end) {
                    let tag = reader.uint32();
                    if (tag === error)
                        break;
                    switch (tag >>> 3) {
                    case 1: {
                            message.team = reader.uint32();
                            break;
                        }
                    case 2: {
                            message.role = reader.uint32();
                            break;
                        }
                    default:
                        reader.skipType(tag & 7, long);
                        break;
                    }
                }
                return message;
            };

            /**
             * Verifies a TAKConfig message.
             * @function verify
             * @memberof meshtastic.ModuleConfig.TAKConfig
             * @static
             * @param {Object.<string,*>} message Plain object to verify
             * @returns {string|null} `null` if valid, otherwise the reason why it is not
             */
            TAKConfig.verify = function verify(message, long) {
                if (typeof message !== "object" || message === null)
                    return "object expected";
                if (long === undefined)
                    long = 0;
                if (long > $util.recursionLimit)
                    return "maximum nesting depth exceeded";
                if (message.team != null && Object.hasOwnProperty.call(message, "team"))
                    if (!$util.isInteger(message.team))
                        return "team: integer expected";
                if (message.role != null && Object.hasOwnProperty.call(message, "role"))
                    if (!$util.isInteger(message.role))
                        return "role: integer expected";
                return null;
            };

            /**
             * Gets the default type url for TAKConfig
             * @function getTypeUrl
             * @memberof meshtastic.ModuleConfig.TAKConfig
             * @static
             * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
             * @returns {string} The default type url
             */
            TAKConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
                if (typeUrlPrefix === undefined) {
                    typeUrlPrefix = "type.googleapis.com";
                }
                return typeUrlPrefix + "/meshtastic.ModuleConfig.TAKConfig";
            };

            return TAKConfig;
        })();

        return ModuleConfig;
    })();

    meshtastic.LocalConfig = (function() {

        /**
         * Properties of a LocalConfig.
         * @memberof meshtastic
         * @interface ILocalConfig
         * @property {meshtastic.Config.IDeviceConfig|null} [device] LocalConfig device
         * @property {meshtastic.Config.IPositionConfig|null} [position] LocalConfig position
         * @property {meshtastic.Config.IPowerConfig|null} [power] LocalConfig power
         * @property {meshtastic.Config.INetworkConfig|null} [network] LocalConfig network
         * @property {meshtastic.Config.IDisplayConfig|null} [display] LocalConfig display
         * @property {meshtastic.Config.ILoRaConfig|null} [lora] LocalConfig lora
         * @property {meshtastic.Config.IBluetoothConfig|null} [bluetooth] LocalConfig bluetooth
         * @property {number|null} [version] LocalConfig version
         * @property {meshtastic.Config.ISecurityConfig|null} [security] LocalConfig security
         */

        /**
         * Constructs a new LocalConfig.
         * @memberof meshtastic
         * @classdesc Represents a LocalConfig.
         * @implements ILocalConfig
         * @constructor
         * @param {meshtastic.ILocalConfig=} [properties] Properties to set
         */
        function LocalConfig(properties) {
            if (properties)
                for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                    if (properties[keys[i]] != null && keys[i] !== "__proto__")
                        this[keys[i]] = properties[keys[i]];
        }

        /**
         * LocalConfig device.
         * @member {meshtastic.Config.IDeviceConfig|null|undefined} device
         * @memberof meshtastic.LocalConfig
         * @instance
         */
        LocalConfig.prototype.device = null;

        /**
         * LocalConfig position.
         * @member {meshtastic.Config.IPositionConfig|null|undefined} position
         * @memberof meshtastic.LocalConfig
         * @instance
         */
        LocalConfig.prototype.position = null;

        /**
         * LocalConfig power.
         * @member {meshtastic.Config.IPowerConfig|null|undefined} power
         * @memberof meshtastic.LocalConfig
         * @instance
         */
        LocalConfig.prototype.power = null;

        /**
         * LocalConfig network.
         * @member {meshtastic.Config.INetworkConfig|null|undefined} network
         * @memberof meshtastic.LocalConfig
         * @instance
         */
        LocalConfig.prototype.network = null;

        /**
         * LocalConfig display.
         * @member {meshtastic.Config.IDisplayConfig|null|undefined} display
         * @memberof meshtastic.LocalConfig
         * @instance
         */
        LocalConfig.prototype.display = null;

        /**
         * LocalConfig lora.
         * @member {meshtastic.Config.ILoRaConfig|null|undefined} lora
         * @memberof meshtastic.LocalConfig
         * @instance
         */
        LocalConfig.prototype.lora = null;

        /**
         * LocalConfig bluetooth.
         * @member {meshtastic.Config.IBluetoothConfig|null|undefined} bluetooth
         * @memberof meshtastic.LocalConfig
         * @instance
         */
        LocalConfig.prototype.bluetooth = null;

        /**
         * LocalConfig version.
         * @member {number} version
         * @memberof meshtastic.LocalConfig
         * @instance
         */
        LocalConfig.prototype.version = 0;

        /**
         * LocalConfig security.
         * @member {meshtastic.Config.ISecurityConfig|null|undefined} security
         * @memberof meshtastic.LocalConfig
         * @instance
         */
        LocalConfig.prototype.security = null;

        /**
         * Creates a new LocalConfig instance using the specified properties.
         * @function create
         * @memberof meshtastic.LocalConfig
         * @static
         * @param {meshtastic.ILocalConfig=} [properties] Properties to set
         * @returns {meshtastic.LocalConfig} LocalConfig instance
         */
        LocalConfig.create = function create(properties) {
            return new LocalConfig(properties);
        };

        /**
         * Encodes the specified LocalConfig message. Does not implicitly {@link meshtastic.LocalConfig.verify|verify} messages.
         * @function encode
         * @memberof meshtastic.LocalConfig
         * @static
         * @param {meshtastic.ILocalConfig} message LocalConfig message or plain object to encode
         * @param {$protobuf.Writer} [writer] Writer to encode to
         * @returns {$protobuf.Writer} Writer
         */
        LocalConfig.encode = function encode(message, writer, q) {
            if (!writer)
                writer = $Writer.create();
            if (q === undefined)
                q = 0;
            if (q > $util.recursionLimit)
                throw Error("max depth exceeded");
            if (message.device != null && Object.hasOwnProperty.call(message, "device"))
                $root.meshtastic.Config.DeviceConfig.encode(message.device, writer.uint32(/* id 1, wireType 2 =*/10).fork(), q + 1).ldelim();
            if (message.position != null && Object.hasOwnProperty.call(message, "position"))
                $root.meshtastic.Config.PositionConfig.encode(message.position, writer.uint32(/* id 2, wireType 2 =*/18).fork(), q + 1).ldelim();
            if (message.power != null && Object.hasOwnProperty.call(message, "power"))
                $root.meshtastic.Config.PowerConfig.encode(message.power, writer.uint32(/* id 3, wireType 2 =*/26).fork(), q + 1).ldelim();
            if (message.network != null && Object.hasOwnProperty.call(message, "network"))
                $root.meshtastic.Config.NetworkConfig.encode(message.network, writer.uint32(/* id 4, wireType 2 =*/34).fork(), q + 1).ldelim();
            if (message.display != null && Object.hasOwnProperty.call(message, "display"))
                $root.meshtastic.Config.DisplayConfig.encode(message.display, writer.uint32(/* id 5, wireType 2 =*/42).fork(), q + 1).ldelim();
            if (message.lora != null && Object.hasOwnProperty.call(message, "lora"))
                $root.meshtastic.Config.LoRaConfig.encode(message.lora, writer.uint32(/* id 6, wireType 2 =*/50).fork(), q + 1).ldelim();
            if (message.bluetooth != null && Object.hasOwnProperty.call(message, "bluetooth"))
                $root.meshtastic.Config.BluetoothConfig.encode(message.bluetooth, writer.uint32(/* id 7, wireType 2 =*/58).fork(), q + 1).ldelim();
            if (message.version != null && Object.hasOwnProperty.call(message, "version"))
                writer.uint32(/* id 8, wireType 0 =*/64).uint32(message.version);
            if (message.security != null && Object.hasOwnProperty.call(message, "security"))
                $root.meshtastic.Config.SecurityConfig.encode(message.security, writer.uint32(/* id 9, wireType 2 =*/74).fork(), q + 1).ldelim();
            return writer;
        };

        /**
         * Decodes a LocalConfig message from the specified reader or buffer.
         * @function decode
         * @memberof meshtastic.LocalConfig
         * @static
         * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
         * @param {number} [length] Message length if known beforehand
         * @returns {meshtastic.LocalConfig} LocalConfig
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        LocalConfig.decode = function decode(reader, length, error, long) {
            if (!(reader instanceof $Reader))
                reader = $Reader.create(reader);
            if (long === undefined)
                long = 0;
            if (long > $Reader.recursionLimit)
                throw Error("maximum nesting depth exceeded");
            let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.LocalConfig();
            while (reader.pos < end) {
                let tag = reader.uint32();
                if (tag === error)
                    break;
                switch (tag >>> 3) {
                case 1: {
                        message.device = $root.meshtastic.Config.DeviceConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 2: {
                        message.position = $root.meshtastic.Config.PositionConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 3: {
                        message.power = $root.meshtastic.Config.PowerConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 4: {
                        message.network = $root.meshtastic.Config.NetworkConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 5: {
                        message.display = $root.meshtastic.Config.DisplayConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 6: {
                        message.lora = $root.meshtastic.Config.LoRaConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 7: {
                        message.bluetooth = $root.meshtastic.Config.BluetoothConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 8: {
                        message.version = reader.uint32();
                        break;
                    }
                case 9: {
                        message.security = $root.meshtastic.Config.SecurityConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                default:
                    reader.skipType(tag & 7, long);
                    break;
                }
            }
            return message;
        };

        /**
         * Verifies a LocalConfig message.
         * @function verify
         * @memberof meshtastic.LocalConfig
         * @static
         * @param {Object.<string,*>} message Plain object to verify
         * @returns {string|null} `null` if valid, otherwise the reason why it is not
         */
        LocalConfig.verify = function verify(message, long) {
            if (typeof message !== "object" || message === null)
                return "object expected";
            if (long === undefined)
                long = 0;
            if (long > $util.recursionLimit)
                return "maximum nesting depth exceeded";
            if (message.device != null && Object.hasOwnProperty.call(message, "device")) {
                let error = $root.meshtastic.Config.DeviceConfig.verify(message.device, long + 1);
                if (error)
                    return "device." + error;
            }
            if (message.position != null && Object.hasOwnProperty.call(message, "position")) {
                let error = $root.meshtastic.Config.PositionConfig.verify(message.position, long + 1);
                if (error)
                    return "position." + error;
            }
            if (message.power != null && Object.hasOwnProperty.call(message, "power")) {
                let error = $root.meshtastic.Config.PowerConfig.verify(message.power, long + 1);
                if (error)
                    return "power." + error;
            }
            if (message.network != null && Object.hasOwnProperty.call(message, "network")) {
                let error = $root.meshtastic.Config.NetworkConfig.verify(message.network, long + 1);
                if (error)
                    return "network." + error;
            }
            if (message.display != null && Object.hasOwnProperty.call(message, "display")) {
                let error = $root.meshtastic.Config.DisplayConfig.verify(message.display, long + 1);
                if (error)
                    return "display." + error;
            }
            if (message.lora != null && Object.hasOwnProperty.call(message, "lora")) {
                let error = $root.meshtastic.Config.LoRaConfig.verify(message.lora, long + 1);
                if (error)
                    return "lora." + error;
            }
            if (message.bluetooth != null && Object.hasOwnProperty.call(message, "bluetooth")) {
                let error = $root.meshtastic.Config.BluetoothConfig.verify(message.bluetooth, long + 1);
                if (error)
                    return "bluetooth." + error;
            }
            if (message.version != null && Object.hasOwnProperty.call(message, "version"))
                if (!$util.isInteger(message.version))
                    return "version: integer expected";
            if (message.security != null && Object.hasOwnProperty.call(message, "security")) {
                let error = $root.meshtastic.Config.SecurityConfig.verify(message.security, long + 1);
                if (error)
                    return "security." + error;
            }
            return null;
        };

        /**
         * Gets the default type url for LocalConfig
         * @function getTypeUrl
         * @memberof meshtastic.LocalConfig
         * @static
         * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns {string} The default type url
         */
        LocalConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
            if (typeUrlPrefix === undefined) {
                typeUrlPrefix = "type.googleapis.com";
            }
            return typeUrlPrefix + "/meshtastic.LocalConfig";
        };

        return LocalConfig;
    })();

    meshtastic.LocalModuleConfig = (function() {

        /**
         * Properties of a LocalModuleConfig.
         * @memberof meshtastic
         * @interface ILocalModuleConfig
         * @property {meshtastic.ModuleConfig.IMQTTConfig|null} [mqtt] LocalModuleConfig mqtt
         * @property {meshtastic.ModuleConfig.ISerialConfig|null} [serial] LocalModuleConfig serial
         * @property {meshtastic.ModuleConfig.IExternalNotificationConfig|null} [externalNotification] LocalModuleConfig externalNotification
         * @property {meshtastic.ModuleConfig.IStoreForwardConfig|null} [storeForward] LocalModuleConfig storeForward
         * @property {meshtastic.ModuleConfig.IRangeTestConfig|null} [rangeTest] LocalModuleConfig rangeTest
         * @property {meshtastic.ModuleConfig.ITelemetryConfig|null} [telemetry] LocalModuleConfig telemetry
         * @property {meshtastic.ModuleConfig.ICannedMessageConfig|null} [cannedMessage] LocalModuleConfig cannedMessage
         * @property {meshtastic.ModuleConfig.IAudioConfig|null} [audio] LocalModuleConfig audio
         * @property {meshtastic.ModuleConfig.IRemoteHardwareConfig|null} [remoteHardware] LocalModuleConfig remoteHardware
         * @property {meshtastic.ModuleConfig.INeighborInfoConfig|null} [neighborInfo] LocalModuleConfig neighborInfo
         * @property {meshtastic.ModuleConfig.IAmbientLightingConfig|null} [ambientLighting] LocalModuleConfig ambientLighting
         * @property {meshtastic.ModuleConfig.IDetectionSensorConfig|null} [detectionSensor] LocalModuleConfig detectionSensor
         * @property {meshtastic.ModuleConfig.IPaxcounterConfig|null} [paxcounter] LocalModuleConfig paxcounter
         * @property {meshtastic.ModuleConfig.IStatusMessageConfig|null} [statusmessage] LocalModuleConfig statusmessage
         * @property {meshtastic.ModuleConfig.ITrafficManagementConfig|null} [trafficManagement] LocalModuleConfig trafficManagement
         * @property {meshtastic.ModuleConfig.ITAKConfig|null} [tak] LocalModuleConfig tak
         * @property {number|null} [version] LocalModuleConfig version
         */

        /**
         * Constructs a new LocalModuleConfig.
         * @memberof meshtastic
         * @classdesc Represents a LocalModuleConfig.
         * @implements ILocalModuleConfig
         * @constructor
         * @param {meshtastic.ILocalModuleConfig=} [properties] Properties to set
         */
        function LocalModuleConfig(properties) {
            if (properties)
                for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                    if (properties[keys[i]] != null && keys[i] !== "__proto__")
                        this[keys[i]] = properties[keys[i]];
        }

        /**
         * LocalModuleConfig mqtt.
         * @member {meshtastic.ModuleConfig.IMQTTConfig|null|undefined} mqtt
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.mqtt = null;

        /**
         * LocalModuleConfig serial.
         * @member {meshtastic.ModuleConfig.ISerialConfig|null|undefined} serial
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.serial = null;

        /**
         * LocalModuleConfig externalNotification.
         * @member {meshtastic.ModuleConfig.IExternalNotificationConfig|null|undefined} externalNotification
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.externalNotification = null;

        /**
         * LocalModuleConfig storeForward.
         * @member {meshtastic.ModuleConfig.IStoreForwardConfig|null|undefined} storeForward
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.storeForward = null;

        /**
         * LocalModuleConfig rangeTest.
         * @member {meshtastic.ModuleConfig.IRangeTestConfig|null|undefined} rangeTest
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.rangeTest = null;

        /**
         * LocalModuleConfig telemetry.
         * @member {meshtastic.ModuleConfig.ITelemetryConfig|null|undefined} telemetry
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.telemetry = null;

        /**
         * LocalModuleConfig cannedMessage.
         * @member {meshtastic.ModuleConfig.ICannedMessageConfig|null|undefined} cannedMessage
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.cannedMessage = null;

        /**
         * LocalModuleConfig audio.
         * @member {meshtastic.ModuleConfig.IAudioConfig|null|undefined} audio
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.audio = null;

        /**
         * LocalModuleConfig remoteHardware.
         * @member {meshtastic.ModuleConfig.IRemoteHardwareConfig|null|undefined} remoteHardware
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.remoteHardware = null;

        /**
         * LocalModuleConfig neighborInfo.
         * @member {meshtastic.ModuleConfig.INeighborInfoConfig|null|undefined} neighborInfo
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.neighborInfo = null;

        /**
         * LocalModuleConfig ambientLighting.
         * @member {meshtastic.ModuleConfig.IAmbientLightingConfig|null|undefined} ambientLighting
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.ambientLighting = null;

        /**
         * LocalModuleConfig detectionSensor.
         * @member {meshtastic.ModuleConfig.IDetectionSensorConfig|null|undefined} detectionSensor
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.detectionSensor = null;

        /**
         * LocalModuleConfig paxcounter.
         * @member {meshtastic.ModuleConfig.IPaxcounterConfig|null|undefined} paxcounter
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.paxcounter = null;

        /**
         * LocalModuleConfig statusmessage.
         * @member {meshtastic.ModuleConfig.IStatusMessageConfig|null|undefined} statusmessage
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.statusmessage = null;

        /**
         * LocalModuleConfig trafficManagement.
         * @member {meshtastic.ModuleConfig.ITrafficManagementConfig|null|undefined} trafficManagement
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.trafficManagement = null;

        /**
         * LocalModuleConfig tak.
         * @member {meshtastic.ModuleConfig.ITAKConfig|null|undefined} tak
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.tak = null;

        /**
         * LocalModuleConfig version.
         * @member {number} version
         * @memberof meshtastic.LocalModuleConfig
         * @instance
         */
        LocalModuleConfig.prototype.version = 0;

        /**
         * Creates a new LocalModuleConfig instance using the specified properties.
         * @function create
         * @memberof meshtastic.LocalModuleConfig
         * @static
         * @param {meshtastic.ILocalModuleConfig=} [properties] Properties to set
         * @returns {meshtastic.LocalModuleConfig} LocalModuleConfig instance
         */
        LocalModuleConfig.create = function create(properties) {
            return new LocalModuleConfig(properties);
        };

        /**
         * Encodes the specified LocalModuleConfig message. Does not implicitly {@link meshtastic.LocalModuleConfig.verify|verify} messages.
         * @function encode
         * @memberof meshtastic.LocalModuleConfig
         * @static
         * @param {meshtastic.ILocalModuleConfig} message LocalModuleConfig message or plain object to encode
         * @param {$protobuf.Writer} [writer] Writer to encode to
         * @returns {$protobuf.Writer} Writer
         */
        LocalModuleConfig.encode = function encode(message, writer, q) {
            if (!writer)
                writer = $Writer.create();
            if (q === undefined)
                q = 0;
            if (q > $util.recursionLimit)
                throw Error("max depth exceeded");
            if (message.mqtt != null && Object.hasOwnProperty.call(message, "mqtt"))
                $root.meshtastic.ModuleConfig.MQTTConfig.encode(message.mqtt, writer.uint32(/* id 1, wireType 2 =*/10).fork(), q + 1).ldelim();
            if (message.serial != null && Object.hasOwnProperty.call(message, "serial"))
                $root.meshtastic.ModuleConfig.SerialConfig.encode(message.serial, writer.uint32(/* id 2, wireType 2 =*/18).fork(), q + 1).ldelim();
            if (message.externalNotification != null && Object.hasOwnProperty.call(message, "externalNotification"))
                $root.meshtastic.ModuleConfig.ExternalNotificationConfig.encode(message.externalNotification, writer.uint32(/* id 3, wireType 2 =*/26).fork(), q + 1).ldelim();
            if (message.storeForward != null && Object.hasOwnProperty.call(message, "storeForward"))
                $root.meshtastic.ModuleConfig.StoreForwardConfig.encode(message.storeForward, writer.uint32(/* id 4, wireType 2 =*/34).fork(), q + 1).ldelim();
            if (message.rangeTest != null && Object.hasOwnProperty.call(message, "rangeTest"))
                $root.meshtastic.ModuleConfig.RangeTestConfig.encode(message.rangeTest, writer.uint32(/* id 5, wireType 2 =*/42).fork(), q + 1).ldelim();
            if (message.telemetry != null && Object.hasOwnProperty.call(message, "telemetry"))
                $root.meshtastic.ModuleConfig.TelemetryConfig.encode(message.telemetry, writer.uint32(/* id 6, wireType 2 =*/50).fork(), q + 1).ldelim();
            if (message.cannedMessage != null && Object.hasOwnProperty.call(message, "cannedMessage"))
                $root.meshtastic.ModuleConfig.CannedMessageConfig.encode(message.cannedMessage, writer.uint32(/* id 7, wireType 2 =*/58).fork(), q + 1).ldelim();
            if (message.version != null && Object.hasOwnProperty.call(message, "version"))
                writer.uint32(/* id 8, wireType 0 =*/64).uint32(message.version);
            if (message.audio != null && Object.hasOwnProperty.call(message, "audio"))
                $root.meshtastic.ModuleConfig.AudioConfig.encode(message.audio, writer.uint32(/* id 9, wireType 2 =*/74).fork(), q + 1).ldelim();
            if (message.remoteHardware != null && Object.hasOwnProperty.call(message, "remoteHardware"))
                $root.meshtastic.ModuleConfig.RemoteHardwareConfig.encode(message.remoteHardware, writer.uint32(/* id 10, wireType 2 =*/82).fork(), q + 1).ldelim();
            if (message.neighborInfo != null && Object.hasOwnProperty.call(message, "neighborInfo"))
                $root.meshtastic.ModuleConfig.NeighborInfoConfig.encode(message.neighborInfo, writer.uint32(/* id 11, wireType 2 =*/90).fork(), q + 1).ldelim();
            if (message.ambientLighting != null && Object.hasOwnProperty.call(message, "ambientLighting"))
                $root.meshtastic.ModuleConfig.AmbientLightingConfig.encode(message.ambientLighting, writer.uint32(/* id 12, wireType 2 =*/98).fork(), q + 1).ldelim();
            if (message.detectionSensor != null && Object.hasOwnProperty.call(message, "detectionSensor"))
                $root.meshtastic.ModuleConfig.DetectionSensorConfig.encode(message.detectionSensor, writer.uint32(/* id 13, wireType 2 =*/106).fork(), q + 1).ldelim();
            if (message.paxcounter != null && Object.hasOwnProperty.call(message, "paxcounter"))
                $root.meshtastic.ModuleConfig.PaxcounterConfig.encode(message.paxcounter, writer.uint32(/* id 14, wireType 2 =*/114).fork(), q + 1).ldelim();
            if (message.statusmessage != null && Object.hasOwnProperty.call(message, "statusmessage"))
                $root.meshtastic.ModuleConfig.StatusMessageConfig.encode(message.statusmessage, writer.uint32(/* id 15, wireType 2 =*/122).fork(), q + 1).ldelim();
            if (message.trafficManagement != null && Object.hasOwnProperty.call(message, "trafficManagement"))
                $root.meshtastic.ModuleConfig.TrafficManagementConfig.encode(message.trafficManagement, writer.uint32(/* id 16, wireType 2 =*/130).fork(), q + 1).ldelim();
            if (message.tak != null && Object.hasOwnProperty.call(message, "tak"))
                $root.meshtastic.ModuleConfig.TAKConfig.encode(message.tak, writer.uint32(/* id 17, wireType 2 =*/138).fork(), q + 1).ldelim();
            return writer;
        };

        /**
         * Decodes a LocalModuleConfig message from the specified reader or buffer.
         * @function decode
         * @memberof meshtastic.LocalModuleConfig
         * @static
         * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
         * @param {number} [length] Message length if known beforehand
         * @returns {meshtastic.LocalModuleConfig} LocalModuleConfig
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        LocalModuleConfig.decode = function decode(reader, length, error, long) {
            if (!(reader instanceof $Reader))
                reader = $Reader.create(reader);
            if (long === undefined)
                long = 0;
            if (long > $Reader.recursionLimit)
                throw Error("maximum nesting depth exceeded");
            let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.LocalModuleConfig();
            while (reader.pos < end) {
                let tag = reader.uint32();
                if (tag === error)
                    break;
                switch (tag >>> 3) {
                case 1: {
                        message.mqtt = $root.meshtastic.ModuleConfig.MQTTConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 2: {
                        message.serial = $root.meshtastic.ModuleConfig.SerialConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 3: {
                        message.externalNotification = $root.meshtastic.ModuleConfig.ExternalNotificationConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 4: {
                        message.storeForward = $root.meshtastic.ModuleConfig.StoreForwardConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 5: {
                        message.rangeTest = $root.meshtastic.ModuleConfig.RangeTestConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 6: {
                        message.telemetry = $root.meshtastic.ModuleConfig.TelemetryConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 7: {
                        message.cannedMessage = $root.meshtastic.ModuleConfig.CannedMessageConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 9: {
                        message.audio = $root.meshtastic.ModuleConfig.AudioConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 10: {
                        message.remoteHardware = $root.meshtastic.ModuleConfig.RemoteHardwareConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 11: {
                        message.neighborInfo = $root.meshtastic.ModuleConfig.NeighborInfoConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 12: {
                        message.ambientLighting = $root.meshtastic.ModuleConfig.AmbientLightingConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 13: {
                        message.detectionSensor = $root.meshtastic.ModuleConfig.DetectionSensorConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 14: {
                        message.paxcounter = $root.meshtastic.ModuleConfig.PaxcounterConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 15: {
                        message.statusmessage = $root.meshtastic.ModuleConfig.StatusMessageConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 16: {
                        message.trafficManagement = $root.meshtastic.ModuleConfig.TrafficManagementConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 17: {
                        message.tak = $root.meshtastic.ModuleConfig.TAKConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 8: {
                        message.version = reader.uint32();
                        break;
                    }
                default:
                    reader.skipType(tag & 7, long);
                    break;
                }
            }
            return message;
        };

        /**
         * Verifies a LocalModuleConfig message.
         * @function verify
         * @memberof meshtastic.LocalModuleConfig
         * @static
         * @param {Object.<string,*>} message Plain object to verify
         * @returns {string|null} `null` if valid, otherwise the reason why it is not
         */
        LocalModuleConfig.verify = function verify(message, long) {
            if (typeof message !== "object" || message === null)
                return "object expected";
            if (long === undefined)
                long = 0;
            if (long > $util.recursionLimit)
                return "maximum nesting depth exceeded";
            if (message.mqtt != null && Object.hasOwnProperty.call(message, "mqtt")) {
                let error = $root.meshtastic.ModuleConfig.MQTTConfig.verify(message.mqtt, long + 1);
                if (error)
                    return "mqtt." + error;
            }
            if (message.serial != null && Object.hasOwnProperty.call(message, "serial")) {
                let error = $root.meshtastic.ModuleConfig.SerialConfig.verify(message.serial, long + 1);
                if (error)
                    return "serial." + error;
            }
            if (message.externalNotification != null && Object.hasOwnProperty.call(message, "externalNotification")) {
                let error = $root.meshtastic.ModuleConfig.ExternalNotificationConfig.verify(message.externalNotification, long + 1);
                if (error)
                    return "externalNotification." + error;
            }
            if (message.storeForward != null && Object.hasOwnProperty.call(message, "storeForward")) {
                let error = $root.meshtastic.ModuleConfig.StoreForwardConfig.verify(message.storeForward, long + 1);
                if (error)
                    return "storeForward." + error;
            }
            if (message.rangeTest != null && Object.hasOwnProperty.call(message, "rangeTest")) {
                let error = $root.meshtastic.ModuleConfig.RangeTestConfig.verify(message.rangeTest, long + 1);
                if (error)
                    return "rangeTest." + error;
            }
            if (message.telemetry != null && Object.hasOwnProperty.call(message, "telemetry")) {
                let error = $root.meshtastic.ModuleConfig.TelemetryConfig.verify(message.telemetry, long + 1);
                if (error)
                    return "telemetry." + error;
            }
            if (message.cannedMessage != null && Object.hasOwnProperty.call(message, "cannedMessage")) {
                let error = $root.meshtastic.ModuleConfig.CannedMessageConfig.verify(message.cannedMessage, long + 1);
                if (error)
                    return "cannedMessage." + error;
            }
            if (message.audio != null && Object.hasOwnProperty.call(message, "audio")) {
                let error = $root.meshtastic.ModuleConfig.AudioConfig.verify(message.audio, long + 1);
                if (error)
                    return "audio." + error;
            }
            if (message.remoteHardware != null && Object.hasOwnProperty.call(message, "remoteHardware")) {
                let error = $root.meshtastic.ModuleConfig.RemoteHardwareConfig.verify(message.remoteHardware, long + 1);
                if (error)
                    return "remoteHardware." + error;
            }
            if (message.neighborInfo != null && Object.hasOwnProperty.call(message, "neighborInfo")) {
                let error = $root.meshtastic.ModuleConfig.NeighborInfoConfig.verify(message.neighborInfo, long + 1);
                if (error)
                    return "neighborInfo." + error;
            }
            if (message.ambientLighting != null && Object.hasOwnProperty.call(message, "ambientLighting")) {
                let error = $root.meshtastic.ModuleConfig.AmbientLightingConfig.verify(message.ambientLighting, long + 1);
                if (error)
                    return "ambientLighting." + error;
            }
            if (message.detectionSensor != null && Object.hasOwnProperty.call(message, "detectionSensor")) {
                let error = $root.meshtastic.ModuleConfig.DetectionSensorConfig.verify(message.detectionSensor, long + 1);
                if (error)
                    return "detectionSensor." + error;
            }
            if (message.paxcounter != null && Object.hasOwnProperty.call(message, "paxcounter")) {
                let error = $root.meshtastic.ModuleConfig.PaxcounterConfig.verify(message.paxcounter, long + 1);
                if (error)
                    return "paxcounter." + error;
            }
            if (message.statusmessage != null && Object.hasOwnProperty.call(message, "statusmessage")) {
                let error = $root.meshtastic.ModuleConfig.StatusMessageConfig.verify(message.statusmessage, long + 1);
                if (error)
                    return "statusmessage." + error;
            }
            if (message.trafficManagement != null && Object.hasOwnProperty.call(message, "trafficManagement")) {
                let error = $root.meshtastic.ModuleConfig.TrafficManagementConfig.verify(message.trafficManagement, long + 1);
                if (error)
                    return "trafficManagement." + error;
            }
            if (message.tak != null && Object.hasOwnProperty.call(message, "tak")) {
                let error = $root.meshtastic.ModuleConfig.TAKConfig.verify(message.tak, long + 1);
                if (error)
                    return "tak." + error;
            }
            if (message.version != null && Object.hasOwnProperty.call(message, "version"))
                if (!$util.isInteger(message.version))
                    return "version: integer expected";
            return null;
        };

        /**
         * Gets the default type url for LocalModuleConfig
         * @function getTypeUrl
         * @memberof meshtastic.LocalModuleConfig
         * @static
         * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns {string} The default type url
         */
        LocalModuleConfig.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
            if (typeUrlPrefix === undefined) {
                typeUrlPrefix = "type.googleapis.com";
            }
            return typeUrlPrefix + "/meshtastic.LocalModuleConfig";
        };

        return LocalModuleConfig;
    })();

    meshtastic.ChannelFile = (function() {

        /**
         * Properties of a ChannelFile.
         * @memberof meshtastic
         * @interface IChannelFile
         * @property {Array.<meshtastic.IChannel>|null} [channels] ChannelFile channels
         * @property {number|null} [version] ChannelFile version
         */

        /**
         * Constructs a new ChannelFile.
         * @memberof meshtastic
         * @classdesc Represents a ChannelFile.
         * @implements IChannelFile
         * @constructor
         * @param {meshtastic.IChannelFile=} [properties] Properties to set
         */
        function ChannelFile(properties) {
            this.channels = [];
            if (properties)
                for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                    if (properties[keys[i]] != null && keys[i] !== "__proto__")
                        this[keys[i]] = properties[keys[i]];
        }

        /**
         * ChannelFile channels.
         * @member {Array.<meshtastic.IChannel>} channels
         * @memberof meshtastic.ChannelFile
         * @instance
         */
        ChannelFile.prototype.channels = $util.emptyArray;

        /**
         * ChannelFile version.
         * @member {number} version
         * @memberof meshtastic.ChannelFile
         * @instance
         */
        ChannelFile.prototype.version = 0;

        /**
         * Creates a new ChannelFile instance using the specified properties.
         * @function create
         * @memberof meshtastic.ChannelFile
         * @static
         * @param {meshtastic.IChannelFile=} [properties] Properties to set
         * @returns {meshtastic.ChannelFile} ChannelFile instance
         */
        ChannelFile.create = function create(properties) {
            return new ChannelFile(properties);
        };

        /**
         * Encodes the specified ChannelFile message. Does not implicitly {@link meshtastic.ChannelFile.verify|verify} messages.
         * @function encode
         * @memberof meshtastic.ChannelFile
         * @static
         * @param {meshtastic.IChannelFile} message ChannelFile message or plain object to encode
         * @param {$protobuf.Writer} [writer] Writer to encode to
         * @returns {$protobuf.Writer} Writer
         */
        ChannelFile.encode = function encode(message, writer, q) {
            if (!writer)
                writer = $Writer.create();
            if (q === undefined)
                q = 0;
            if (q > $util.recursionLimit)
                throw Error("max depth exceeded");
            if (message.channels != null && message.channels.length)
                for (let i = 0; i < message.channels.length; ++i)
                    $root.meshtastic.Channel.encode(message.channels[i], writer.uint32(/* id 1, wireType 2 =*/10).fork(), q + 1).ldelim();
            if (message.version != null && Object.hasOwnProperty.call(message, "version"))
                writer.uint32(/* id 2, wireType 0 =*/16).uint32(message.version);
            return writer;
        };

        /**
         * Decodes a ChannelFile message from the specified reader or buffer.
         * @function decode
         * @memberof meshtastic.ChannelFile
         * @static
         * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
         * @param {number} [length] Message length if known beforehand
         * @returns {meshtastic.ChannelFile} ChannelFile
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        ChannelFile.decode = function decode(reader, length, error, long) {
            if (!(reader instanceof $Reader))
                reader = $Reader.create(reader);
            if (long === undefined)
                long = 0;
            if (long > $Reader.recursionLimit)
                throw Error("maximum nesting depth exceeded");
            let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.ChannelFile();
            while (reader.pos < end) {
                let tag = reader.uint32();
                if (tag === error)
                    break;
                switch (tag >>> 3) {
                case 1: {
                        if (!(message.channels && message.channels.length))
                            message.channels = [];
                        message.channels.push($root.meshtastic.Channel.decode(reader, reader.uint32(), undefined, long + 1));
                        break;
                    }
                case 2: {
                        message.version = reader.uint32();
                        break;
                    }
                default:
                    reader.skipType(tag & 7, long);
                    break;
                }
            }
            return message;
        };

        /**
         * Verifies a ChannelFile message.
         * @function verify
         * @memberof meshtastic.ChannelFile
         * @static
         * @param {Object.<string,*>} message Plain object to verify
         * @returns {string|null} `null` if valid, otherwise the reason why it is not
         */
        ChannelFile.verify = function verify(message, long) {
            if (typeof message !== "object" || message === null)
                return "object expected";
            if (long === undefined)
                long = 0;
            if (long > $util.recursionLimit)
                return "maximum nesting depth exceeded";
            if (message.channels != null && Object.hasOwnProperty.call(message, "channels")) {
                if (!Array.isArray(message.channels))
                    return "channels: array expected";
                for (let i = 0; i < message.channels.length; ++i) {
                    let error = $root.meshtastic.Channel.verify(message.channels[i], long + 1);
                    if (error)
                        return "channels." + error;
                }
            }
            if (message.version != null && Object.hasOwnProperty.call(message, "version"))
                if (!$util.isInteger(message.version))
                    return "version: integer expected";
            return null;
        };

        /**
         * Gets the default type url for ChannelFile
         * @function getTypeUrl
         * @memberof meshtastic.ChannelFile
         * @static
         * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns {string} The default type url
         */
        ChannelFile.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
            if (typeUrlPrefix === undefined) {
                typeUrlPrefix = "type.googleapis.com";
            }
            return typeUrlPrefix + "/meshtastic.ChannelFile";
        };

        return ChannelFile;
    })();

    meshtastic.User = (function() {

        /**
         * Properties of a User.
         * @memberof meshtastic
         * @interface IUser
         * @property {string|null} [id] User id
         * @property {string|null} [longName] User longName
         * @property {string|null} [shortName] User shortName
         * @property {number|null} [hwModel] User hwModel
         * @property {boolean|null} [isLicensed] User isLicensed
         * @property {number|null} [role] User role
         * @property {Uint8Array|null} [publicKey] User publicKey
         */

        /**
         * Constructs a new User.
         * @memberof meshtastic
         * @classdesc Represents a User.
         * @implements IUser
         * @constructor
         * @param {meshtastic.IUser=} [properties] Properties to set
         */
        function User(properties) {
            if (properties)
                for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                    if (properties[keys[i]] != null && keys[i] !== "__proto__")
                        this[keys[i]] = properties[keys[i]];
        }

        /**
         * User id.
         * @member {string} id
         * @memberof meshtastic.User
         * @instance
         */
        User.prototype.id = "";

        /**
         * User longName.
         * @member {string} longName
         * @memberof meshtastic.User
         * @instance
         */
        User.prototype.longName = "";

        /**
         * User shortName.
         * @member {string} shortName
         * @memberof meshtastic.User
         * @instance
         */
        User.prototype.shortName = "";

        /**
         * User hwModel.
         * @member {number} hwModel
         * @memberof meshtastic.User
         * @instance
         */
        User.prototype.hwModel = 0;

        /**
         * User isLicensed.
         * @member {boolean} isLicensed
         * @memberof meshtastic.User
         * @instance
         */
        User.prototype.isLicensed = false;

        /**
         * User role.
         * @member {number} role
         * @memberof meshtastic.User
         * @instance
         */
        User.prototype.role = 0;

        /**
         * User publicKey.
         * @member {Uint8Array} publicKey
         * @memberof meshtastic.User
         * @instance
         */
        User.prototype.publicKey = $util.newBuffer([]);

        /**
         * Creates a new User instance using the specified properties.
         * @function create
         * @memberof meshtastic.User
         * @static
         * @param {meshtastic.IUser=} [properties] Properties to set
         * @returns {meshtastic.User} User instance
         */
        User.create = function create(properties) {
            return new User(properties);
        };

        /**
         * Encodes the specified User message. Does not implicitly {@link meshtastic.User.verify|verify} messages.
         * @function encode
         * @memberof meshtastic.User
         * @static
         * @param {meshtastic.IUser} message User message or plain object to encode
         * @param {$protobuf.Writer} [writer] Writer to encode to
         * @returns {$protobuf.Writer} Writer
         */
        User.encode = function encode(message, writer, q) {
            if (!writer)
                writer = $Writer.create();
            if (q === undefined)
                q = 0;
            if (q > $util.recursionLimit)
                throw Error("max depth exceeded");
            if (message.id != null && Object.hasOwnProperty.call(message, "id"))
                writer.uint32(/* id 1, wireType 2 =*/10).string(message.id);
            if (message.longName != null && Object.hasOwnProperty.call(message, "longName"))
                writer.uint32(/* id 2, wireType 2 =*/18).string(message.longName);
            if (message.shortName != null && Object.hasOwnProperty.call(message, "shortName"))
                writer.uint32(/* id 3, wireType 2 =*/26).string(message.shortName);
            if (message.hwModel != null && Object.hasOwnProperty.call(message, "hwModel"))
                writer.uint32(/* id 5, wireType 0 =*/40).uint32(message.hwModel);
            if (message.isLicensed != null && Object.hasOwnProperty.call(message, "isLicensed"))
                writer.uint32(/* id 6, wireType 0 =*/48).bool(message.isLicensed);
            if (message.role != null && Object.hasOwnProperty.call(message, "role"))
                writer.uint32(/* id 7, wireType 0 =*/56).uint32(message.role);
            if (message.publicKey != null && Object.hasOwnProperty.call(message, "publicKey"))
                writer.uint32(/* id 8, wireType 2 =*/66).bytes(message.publicKey);
            return writer;
        };

        /**
         * Decodes a User message from the specified reader or buffer.
         * @function decode
         * @memberof meshtastic.User
         * @static
         * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
         * @param {number} [length] Message length if known beforehand
         * @returns {meshtastic.User} User
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        User.decode = function decode(reader, length, error, long) {
            if (!(reader instanceof $Reader))
                reader = $Reader.create(reader);
            if (long === undefined)
                long = 0;
            if (long > $Reader.recursionLimit)
                throw Error("maximum nesting depth exceeded");
            let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.User();
            while (reader.pos < end) {
                let tag = reader.uint32();
                if (tag === error)
                    break;
                switch (tag >>> 3) {
                case 1: {
                        message.id = reader.string();
                        break;
                    }
                case 2: {
                        message.longName = reader.string();
                        break;
                    }
                case 3: {
                        message.shortName = reader.string();
                        break;
                    }
                case 5: {
                        message.hwModel = reader.uint32();
                        break;
                    }
                case 6: {
                        message.isLicensed = reader.bool();
                        break;
                    }
                case 7: {
                        message.role = reader.uint32();
                        break;
                    }
                case 8: {
                        message.publicKey = reader.bytes();
                        break;
                    }
                default:
                    reader.skipType(tag & 7, long);
                    break;
                }
            }
            return message;
        };

        /**
         * Verifies a User message.
         * @function verify
         * @memberof meshtastic.User
         * @static
         * @param {Object.<string,*>} message Plain object to verify
         * @returns {string|null} `null` if valid, otherwise the reason why it is not
         */
        User.verify = function verify(message, long) {
            if (typeof message !== "object" || message === null)
                return "object expected";
            if (long === undefined)
                long = 0;
            if (long > $util.recursionLimit)
                return "maximum nesting depth exceeded";
            if (message.id != null && Object.hasOwnProperty.call(message, "id"))
                if (!$util.isString(message.id))
                    return "id: string expected";
            if (message.longName != null && Object.hasOwnProperty.call(message, "longName"))
                if (!$util.isString(message.longName))
                    return "longName: string expected";
            if (message.shortName != null && Object.hasOwnProperty.call(message, "shortName"))
                if (!$util.isString(message.shortName))
                    return "shortName: string expected";
            if (message.hwModel != null && Object.hasOwnProperty.call(message, "hwModel"))
                if (!$util.isInteger(message.hwModel))
                    return "hwModel: integer expected";
            if (message.isLicensed != null && Object.hasOwnProperty.call(message, "isLicensed"))
                if (typeof message.isLicensed !== "boolean")
                    return "isLicensed: boolean expected";
            if (message.role != null && Object.hasOwnProperty.call(message, "role"))
                if (!$util.isInteger(message.role))
                    return "role: integer expected";
            if (message.publicKey != null && Object.hasOwnProperty.call(message, "publicKey"))
                if (!(message.publicKey && typeof message.publicKey.length === "number" || $util.isString(message.publicKey)))
                    return "publicKey: buffer expected";
            return null;
        };

        /**
         * Gets the default type url for User
         * @function getTypeUrl
         * @memberof meshtastic.User
         * @static
         * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns {string} The default type url
         */
        User.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
            if (typeUrlPrefix === undefined) {
                typeUrlPrefix = "type.googleapis.com";
            }
            return typeUrlPrefix + "/meshtastic.User";
        };

        return User;
    })();

    meshtastic.DeviceProfile = (function() {

        /**
         * Properties of a DeviceProfile.
         * @memberof meshtastic
         * @interface IDeviceProfile
         * @property {string|null} [longName] DeviceProfile longName
         * @property {string|null} [shortName] DeviceProfile shortName
         * @property {string|null} [channelUrl] DeviceProfile channelUrl
         * @property {meshtastic.ILocalConfig|null} [config] DeviceProfile config
         * @property {meshtastic.ILocalModuleConfig|null} [moduleConfig] DeviceProfile moduleConfig
         * @property {meshtastic.IPosition|null} [fixedPosition] DeviceProfile fixedPosition
         * @property {string|null} [ringtone] DeviceProfile ringtone
         * @property {string|null} [cannedMessages] DeviceProfile cannedMessages
         */

        /**
         * Constructs a new DeviceProfile.
         * @memberof meshtastic
         * @classdesc Represents a DeviceProfile.
         * @implements IDeviceProfile
         * @constructor
         * @param {meshtastic.IDeviceProfile=} [properties] Properties to set
         */
        function DeviceProfile(properties) {
            if (properties)
                for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                    if (properties[keys[i]] != null && keys[i] !== "__proto__")
                        this[keys[i]] = properties[keys[i]];
        }

        /**
         * DeviceProfile longName.
         * @member {string} longName
         * @memberof meshtastic.DeviceProfile
         * @instance
         */
        DeviceProfile.prototype.longName = "";

        /**
         * DeviceProfile shortName.
         * @member {string} shortName
         * @memberof meshtastic.DeviceProfile
         * @instance
         */
        DeviceProfile.prototype.shortName = "";

        /**
         * DeviceProfile channelUrl.
         * @member {string} channelUrl
         * @memberof meshtastic.DeviceProfile
         * @instance
         */
        DeviceProfile.prototype.channelUrl = "";

        /**
         * DeviceProfile config.
         * @member {meshtastic.ILocalConfig|null|undefined} config
         * @memberof meshtastic.DeviceProfile
         * @instance
         */
        DeviceProfile.prototype.config = null;

        /**
         * DeviceProfile moduleConfig.
         * @member {meshtastic.ILocalModuleConfig|null|undefined} moduleConfig
         * @memberof meshtastic.DeviceProfile
         * @instance
         */
        DeviceProfile.prototype.moduleConfig = null;

        /**
         * DeviceProfile fixedPosition.
         * @member {meshtastic.IPosition|null|undefined} fixedPosition
         * @memberof meshtastic.DeviceProfile
         * @instance
         */
        DeviceProfile.prototype.fixedPosition = null;

        /**
         * DeviceProfile ringtone.
         * @member {string} ringtone
         * @memberof meshtastic.DeviceProfile
         * @instance
         */
        DeviceProfile.prototype.ringtone = "";

        /**
         * DeviceProfile cannedMessages.
         * @member {string} cannedMessages
         * @memberof meshtastic.DeviceProfile
         * @instance
         */
        DeviceProfile.prototype.cannedMessages = "";

        /**
         * Creates a new DeviceProfile instance using the specified properties.
         * @function create
         * @memberof meshtastic.DeviceProfile
         * @static
         * @param {meshtastic.IDeviceProfile=} [properties] Properties to set
         * @returns {meshtastic.DeviceProfile} DeviceProfile instance
         */
        DeviceProfile.create = function create(properties) {
            return new DeviceProfile(properties);
        };

        /**
         * Encodes the specified DeviceProfile message. Does not implicitly {@link meshtastic.DeviceProfile.verify|verify} messages.
         * @function encode
         * @memberof meshtastic.DeviceProfile
         * @static
         * @param {meshtastic.IDeviceProfile} message DeviceProfile message or plain object to encode
         * @param {$protobuf.Writer} [writer] Writer to encode to
         * @returns {$protobuf.Writer} Writer
         */
        DeviceProfile.encode = function encode(message, writer, q) {
            if (!writer)
                writer = $Writer.create();
            if (q === undefined)
                q = 0;
            if (q > $util.recursionLimit)
                throw Error("max depth exceeded");
            if (message.longName != null && Object.hasOwnProperty.call(message, "longName"))
                writer.uint32(/* id 1, wireType 2 =*/10).string(message.longName);
            if (message.shortName != null && Object.hasOwnProperty.call(message, "shortName"))
                writer.uint32(/* id 2, wireType 2 =*/18).string(message.shortName);
            if (message.channelUrl != null && Object.hasOwnProperty.call(message, "channelUrl"))
                writer.uint32(/* id 3, wireType 2 =*/26).string(message.channelUrl);
            if (message.config != null && Object.hasOwnProperty.call(message, "config"))
                $root.meshtastic.LocalConfig.encode(message.config, writer.uint32(/* id 4, wireType 2 =*/34).fork(), q + 1).ldelim();
            if (message.moduleConfig != null && Object.hasOwnProperty.call(message, "moduleConfig"))
                $root.meshtastic.LocalModuleConfig.encode(message.moduleConfig, writer.uint32(/* id 5, wireType 2 =*/42).fork(), q + 1).ldelim();
            if (message.fixedPosition != null && Object.hasOwnProperty.call(message, "fixedPosition"))
                $root.meshtastic.Position.encode(message.fixedPosition, writer.uint32(/* id 6, wireType 2 =*/50).fork(), q + 1).ldelim();
            if (message.ringtone != null && Object.hasOwnProperty.call(message, "ringtone"))
                writer.uint32(/* id 7, wireType 2 =*/58).string(message.ringtone);
            if (message.cannedMessages != null && Object.hasOwnProperty.call(message, "cannedMessages"))
                writer.uint32(/* id 8, wireType 2 =*/66).string(message.cannedMessages);
            return writer;
        };

        /**
         * Decodes a DeviceProfile message from the specified reader or buffer.
         * @function decode
         * @memberof meshtastic.DeviceProfile
         * @static
         * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
         * @param {number} [length] Message length if known beforehand
         * @returns {meshtastic.DeviceProfile} DeviceProfile
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        DeviceProfile.decode = function decode(reader, length, error, long) {
            if (!(reader instanceof $Reader))
                reader = $Reader.create(reader);
            if (long === undefined)
                long = 0;
            if (long > $Reader.recursionLimit)
                throw Error("maximum nesting depth exceeded");
            let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.DeviceProfile();
            while (reader.pos < end) {
                let tag = reader.uint32();
                if (tag === error)
                    break;
                switch (tag >>> 3) {
                case 1: {
                        message.longName = reader.string();
                        break;
                    }
                case 2: {
                        message.shortName = reader.string();
                        break;
                    }
                case 3: {
                        message.channelUrl = reader.string();
                        break;
                    }
                case 4: {
                        message.config = $root.meshtastic.LocalConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 5: {
                        message.moduleConfig = $root.meshtastic.LocalModuleConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 6: {
                        message.fixedPosition = $root.meshtastic.Position.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 7: {
                        message.ringtone = reader.string();
                        break;
                    }
                case 8: {
                        message.cannedMessages = reader.string();
                        break;
                    }
                default:
                    reader.skipType(tag & 7, long);
                    break;
                }
            }
            return message;
        };

        /**
         * Verifies a DeviceProfile message.
         * @function verify
         * @memberof meshtastic.DeviceProfile
         * @static
         * @param {Object.<string,*>} message Plain object to verify
         * @returns {string|null} `null` if valid, otherwise the reason why it is not
         */
        DeviceProfile.verify = function verify(message, long) {
            if (typeof message !== "object" || message === null)
                return "object expected";
            if (long === undefined)
                long = 0;
            if (long > $util.recursionLimit)
                return "maximum nesting depth exceeded";
            if (message.longName != null && Object.hasOwnProperty.call(message, "longName"))
                if (!$util.isString(message.longName))
                    return "longName: string expected";
            if (message.shortName != null && Object.hasOwnProperty.call(message, "shortName"))
                if (!$util.isString(message.shortName))
                    return "shortName: string expected";
            if (message.channelUrl != null && Object.hasOwnProperty.call(message, "channelUrl"))
                if (!$util.isString(message.channelUrl))
                    return "channelUrl: string expected";
            if (message.config != null && Object.hasOwnProperty.call(message, "config")) {
                let error = $root.meshtastic.LocalConfig.verify(message.config, long + 1);
                if (error)
                    return "config." + error;
            }
            if (message.moduleConfig != null && Object.hasOwnProperty.call(message, "moduleConfig")) {
                let error = $root.meshtastic.LocalModuleConfig.verify(message.moduleConfig, long + 1);
                if (error)
                    return "moduleConfig." + error;
            }
            if (message.fixedPosition != null && Object.hasOwnProperty.call(message, "fixedPosition")) {
                let error = $root.meshtastic.Position.verify(message.fixedPosition, long + 1);
                if (error)
                    return "fixedPosition." + error;
            }
            if (message.ringtone != null && Object.hasOwnProperty.call(message, "ringtone"))
                if (!$util.isString(message.ringtone))
                    return "ringtone: string expected";
            if (message.cannedMessages != null && Object.hasOwnProperty.call(message, "cannedMessages"))
                if (!$util.isString(message.cannedMessages))
                    return "cannedMessages: string expected";
            return null;
        };

        /**
         * Gets the default type url for DeviceProfile
         * @function getTypeUrl
         * @memberof meshtastic.DeviceProfile
         * @static
         * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns {string} The default type url
         */
        DeviceProfile.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
            if (typeUrlPrefix === undefined) {
                typeUrlPrefix = "type.googleapis.com";
            }
            return typeUrlPrefix + "/meshtastic.DeviceProfile";
        };

        return DeviceProfile;
    })();

    meshtastic.BackupPreferences = (function() {

        /**
         * Properties of a BackupPreferences.
         * @memberof meshtastic
         * @interface IBackupPreferences
         * @property {number|null} [version] BackupPreferences version
         * @property {number|null} [timestamp] BackupPreferences timestamp
         * @property {meshtastic.ILocalConfig|null} [config] BackupPreferences config
         * @property {meshtastic.ILocalModuleConfig|null} [moduleConfig] BackupPreferences moduleConfig
         * @property {meshtastic.IChannelFile|null} [channels] BackupPreferences channels
         * @property {meshtastic.IUser|null} [owner] BackupPreferences owner
         */

        /**
         * Constructs a new BackupPreferences.
         * @memberof meshtastic
         * @classdesc Represents a BackupPreferences.
         * @implements IBackupPreferences
         * @constructor
         * @param {meshtastic.IBackupPreferences=} [properties] Properties to set
         */
        function BackupPreferences(properties) {
            if (properties)
                for (let keys = Object.keys(properties), i = 0; i < keys.length; ++i)
                    if (properties[keys[i]] != null && keys[i] !== "__proto__")
                        this[keys[i]] = properties[keys[i]];
        }

        /**
         * BackupPreferences version.
         * @member {number} version
         * @memberof meshtastic.BackupPreferences
         * @instance
         */
        BackupPreferences.prototype.version = 0;

        /**
         * BackupPreferences timestamp.
         * @member {number} timestamp
         * @memberof meshtastic.BackupPreferences
         * @instance
         */
        BackupPreferences.prototype.timestamp = 0;

        /**
         * BackupPreferences config.
         * @member {meshtastic.ILocalConfig|null|undefined} config
         * @memberof meshtastic.BackupPreferences
         * @instance
         */
        BackupPreferences.prototype.config = null;

        /**
         * BackupPreferences moduleConfig.
         * @member {meshtastic.ILocalModuleConfig|null|undefined} moduleConfig
         * @memberof meshtastic.BackupPreferences
         * @instance
         */
        BackupPreferences.prototype.moduleConfig = null;

        /**
         * BackupPreferences channels.
         * @member {meshtastic.IChannelFile|null|undefined} channels
         * @memberof meshtastic.BackupPreferences
         * @instance
         */
        BackupPreferences.prototype.channels = null;

        /**
         * BackupPreferences owner.
         * @member {meshtastic.IUser|null|undefined} owner
         * @memberof meshtastic.BackupPreferences
         * @instance
         */
        BackupPreferences.prototype.owner = null;

        /**
         * Creates a new BackupPreferences instance using the specified properties.
         * @function create
         * @memberof meshtastic.BackupPreferences
         * @static
         * @param {meshtastic.IBackupPreferences=} [properties] Properties to set
         * @returns {meshtastic.BackupPreferences} BackupPreferences instance
         */
        BackupPreferences.create = function create(properties) {
            return new BackupPreferences(properties);
        };

        /**
         * Encodes the specified BackupPreferences message. Does not implicitly {@link meshtastic.BackupPreferences.verify|verify} messages.
         * @function encode
         * @memberof meshtastic.BackupPreferences
         * @static
         * @param {meshtastic.IBackupPreferences} message BackupPreferences message or plain object to encode
         * @param {$protobuf.Writer} [writer] Writer to encode to
         * @returns {$protobuf.Writer} Writer
         */
        BackupPreferences.encode = function encode(message, writer, q) {
            if (!writer)
                writer = $Writer.create();
            if (q === undefined)
                q = 0;
            if (q > $util.recursionLimit)
                throw Error("max depth exceeded");
            if (message.version != null && Object.hasOwnProperty.call(message, "version"))
                writer.uint32(/* id 1, wireType 0 =*/8).uint32(message.version);
            if (message.timestamp != null && Object.hasOwnProperty.call(message, "timestamp"))
                writer.uint32(/* id 2, wireType 5 =*/21).fixed32(message.timestamp);
            if (message.config != null && Object.hasOwnProperty.call(message, "config"))
                $root.meshtastic.LocalConfig.encode(message.config, writer.uint32(/* id 3, wireType 2 =*/26).fork(), q + 1).ldelim();
            if (message.moduleConfig != null && Object.hasOwnProperty.call(message, "moduleConfig"))
                $root.meshtastic.LocalModuleConfig.encode(message.moduleConfig, writer.uint32(/* id 4, wireType 2 =*/34).fork(), q + 1).ldelim();
            if (message.channels != null && Object.hasOwnProperty.call(message, "channels"))
                $root.meshtastic.ChannelFile.encode(message.channels, writer.uint32(/* id 5, wireType 2 =*/42).fork(), q + 1).ldelim();
            if (message.owner != null && Object.hasOwnProperty.call(message, "owner"))
                $root.meshtastic.User.encode(message.owner, writer.uint32(/* id 6, wireType 2 =*/50).fork(), q + 1).ldelim();
            return writer;
        };

        /**
         * Decodes a BackupPreferences message from the specified reader or buffer.
         * @function decode
         * @memberof meshtastic.BackupPreferences
         * @static
         * @param {$protobuf.Reader|Uint8Array} reader Reader or buffer to decode from
         * @param {number} [length] Message length if known beforehand
         * @returns {meshtastic.BackupPreferences} BackupPreferences
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        BackupPreferences.decode = function decode(reader, length, error, long) {
            if (!(reader instanceof $Reader))
                reader = $Reader.create(reader);
            if (long === undefined)
                long = 0;
            if (long > $Reader.recursionLimit)
                throw Error("maximum nesting depth exceeded");
            let end = length === undefined ? reader.len : reader.pos + length, message = new $root.meshtastic.BackupPreferences();
            while (reader.pos < end) {
                let tag = reader.uint32();
                if (tag === error)
                    break;
                switch (tag >>> 3) {
                case 1: {
                        message.version = reader.uint32();
                        break;
                    }
                case 2: {
                        message.timestamp = reader.fixed32();
                        break;
                    }
                case 3: {
                        message.config = $root.meshtastic.LocalConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 4: {
                        message.moduleConfig = $root.meshtastic.LocalModuleConfig.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 5: {
                        message.channels = $root.meshtastic.ChannelFile.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                case 6: {
                        message.owner = $root.meshtastic.User.decode(reader, reader.uint32(), undefined, long + 1);
                        break;
                    }
                default:
                    reader.skipType(tag & 7, long);
                    break;
                }
            }
            return message;
        };

        /**
         * Verifies a BackupPreferences message.
         * @function verify
         * @memberof meshtastic.BackupPreferences
         * @static
         * @param {Object.<string,*>} message Plain object to verify
         * @returns {string|null} `null` if valid, otherwise the reason why it is not
         */
        BackupPreferences.verify = function verify(message, long) {
            if (typeof message !== "object" || message === null)
                return "object expected";
            if (long === undefined)
                long = 0;
            if (long > $util.recursionLimit)
                return "maximum nesting depth exceeded";
            if (message.version != null && Object.hasOwnProperty.call(message, "version"))
                if (!$util.isInteger(message.version))
                    return "version: integer expected";
            if (message.timestamp != null && Object.hasOwnProperty.call(message, "timestamp"))
                if (!$util.isInteger(message.timestamp))
                    return "timestamp: integer expected";
            if (message.config != null && Object.hasOwnProperty.call(message, "config")) {
                let error = $root.meshtastic.LocalConfig.verify(message.config, long + 1);
                if (error)
                    return "config." + error;
            }
            if (message.moduleConfig != null && Object.hasOwnProperty.call(message, "moduleConfig")) {
                let error = $root.meshtastic.LocalModuleConfig.verify(message.moduleConfig, long + 1);
                if (error)
                    return "moduleConfig." + error;
            }
            if (message.channels != null && Object.hasOwnProperty.call(message, "channels")) {
                let error = $root.meshtastic.ChannelFile.verify(message.channels, long + 1);
                if (error)
                    return "channels." + error;
            }
            if (message.owner != null && Object.hasOwnProperty.call(message, "owner")) {
                let error = $root.meshtastic.User.verify(message.owner, long + 1);
                if (error)
                    return "owner." + error;
            }
            return null;
        };

        /**
         * Gets the default type url for BackupPreferences
         * @function getTypeUrl
         * @memberof meshtastic.BackupPreferences
         * @static
         * @param {string} [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns {string} The default type url
         */
        BackupPreferences.getTypeUrl = function getTypeUrl(typeUrlPrefix) {
            if (typeUrlPrefix === undefined) {
                typeUrlPrefix = "type.googleapis.com";
            }
            return typeUrlPrefix + "/meshtastic.BackupPreferences";
        };

        return BackupPreferences;
    })();

    return meshtastic;
})();

export { $root as default };
