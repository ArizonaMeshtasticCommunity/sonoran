/**
 * Meshtastic Protobuf Definitions for browser-based decoding.
 *
 * This file defines the protobuf schema as a JSON descriptor so protobuf.js
 * can decode Android .cfg binary exports without needing to fetch .proto files.
 *
 * Source: https://github.com/meshtastic/protobufs
 * The Android app exports DeviceProfile from clientonly.proto.
 */

window.MeshtasticProto = {
  nested: {
    meshtastic: {
      nested: {

        // ---- Position (minimal, for DeviceProfile.fixed_position) ----
        Position: {
          fields: {
            latitudeI: { type: "sfixed32", id: 1 },
            longitudeI: { type: "sfixed32", id: 2 },
            altitude: { type: "int32", id: 3 },
            time: { type: "fixed32", id: 4 }
          }
        },

        // ---- Channel & ChannelSettings ----
        ModuleSettings: {
          fields: {
            positionPrecision: { type: "uint32", id: 1 },
            isMuted: { type: "bool", id: 2 }
          }
        },

        ChannelSettings: {
          fields: {
            channelNum: { type: "uint32", id: 1 },
            psk: { type: "bytes", id: 2 },
            name: { type: "string", id: 3 },
            id: { type: "fixed32", id: 4 },
            uplinkEnabled: { type: "bool", id: 5 },
            downlinkEnabled: { type: "bool", id: 6 },
            moduleSettings: { type: "ModuleSettings", id: 7 }
          }
        },

        Channel: {
          fields: {
            index: { type: "int32", id: 1 },
            settings: { type: "ChannelSettings", id: 2 },
            role: { type: "Channel.Role", id: 3 }
          },
          nested: {
            Role: {
              values: { DISABLED: 0, PRIMARY: 1, SECONDARY: 2 }
            }
          }
        },

        // ---- ChannelSet (from apponly.proto) ----
        ChannelSet: {
          fields: {
            settings: { rule: "repeated", type: "ChannelSettings", id: 1 },
            loraConfig: { type: "Config.LoRaConfig", id: 2 }
          }
        },

        // ---- Config ----
        Config: {
          nested: {
            DeviceConfig: {
              fields: {
                role: { type: "Config.DeviceConfig.Role", id: 1 },
                serialEnabled: { type: "bool", id: 2 },
                buttonGpio: { type: "uint32", id: 4 },
                buzzerGpio: { type: "uint32", id: 5 },
                rebroadcastMode: { type: "uint32", id: 6 },
                nodeInfoBroadcastSecs: { type: "uint32", id: 7 },
                doubleTapAsButtonPress: { type: "bool", id: 8 },
                isManaged: { type: "bool", id: 9 },
                disableTripleClick: { type: "bool", id: 10 },
                tzdef: { type: "string", id: 11 },
                ledHeartbeatDisabled: { type: "bool", id: 12 },
                buzzerMode: { type: "uint32", id: 13 }
              },
              nested: {
                Role: {
                  values: {
                    CLIENT: 0,
                    CLIENT_MUTE: 1,
                    ROUTER: 2,
                    ROUTER_CLIENT: 3,
                    REPEATER: 4,
                    TRACKER: 5,
                    SENSOR: 6,
                    TAK: 7,
                    CLIENT_HIDDEN: 8,
                    LOST_AND_FOUND: 9,
                    TAK_TRACKER: 10,
                    ROUTER_LATE: 11,
                    CLIENT_BASE: 12
                  }
                }
              }
            },

            PositionConfig: {
              fields: {
                positionBroadcastSecs: { type: "uint32", id: 1 },
                positionBroadcastSmartEnabled: { type: "bool", id: 2 },
                fixedPosition: { type: "bool", id: 3 },
                gpsEnabled: { type: "bool", id: 4 },
                gpsUpdateInterval: { type: "uint32", id: 5 },
                gpsAttemptTime: { type: "uint32", id: 6 },
                positionFlags: { type: "uint32", id: 7 },
                rxGpio: { type: "uint32", id: 8 },
                txGpio: { type: "uint32", id: 9 },
                broadcastSmartMinimumDistance: { type: "uint32", id: 10 },
                broadcastSmartMinimumIntervalSecs: { type: "uint32", id: 11 },
                gpsEnGpio: { type: "uint32", id: 12 },
                gpsMode: { type: "uint32", id: 13 }
              }
            },

            PowerConfig: {
              fields: {
                isPowerSaving: { type: "bool", id: 1 },
                onBatteryShutdownAfterSecs: { type: "uint32", id: 2 },
                adcMultiplierOverride: { type: "float", id: 3 },
                waitBluetoothSecs: { type: "uint32", id: 4 },
                sdsSecs: { type: "uint32", id: 6 },
                lsSecs: { type: "uint32", id: 7 },
                minWakeSecs: { type: "uint32", id: 8 },
                deviceBatteryInaAddress: { type: "uint32", id: 9 },
                powermonEnables: { type: "uint64", id: 32 }
              }
            },

            NetworkConfig: {
              fields: {
                wifiEnabled: { type: "bool", id: 1 },
                wifiSsid: { type: "string", id: 3 },
                wifiPsk: { type: "string", id: 4 },
                ntpServer: { type: "string", id: 5 },
                ethEnabled: { type: "bool", id: 6 },
                addressMode: { type: "uint32", id: 7 }
              }
            },

            DisplayConfig: {
              fields: {
                screenOnSecs: { type: "uint32", id: 1 },
                autoScreenCarouselSecs: { type: "uint32", id: 3 },
                flipScreen: { type: "bool", id: 5 },
                units: { type: "uint32", id: 6 },
                oled: { type: "uint32", id: 7 },
                displaymode: { type: "uint32", id: 8 },
                headingBold: { type: "bool", id: 9 },
                wakeOnTapOrMotion: { type: "bool", id: 10 }
              }
            },

            LoRaConfig: {
              fields: {
                usePreset: { type: "bool", id: 1 },
                modemPreset: { type: "Config.LoRaConfig.ModemPreset", id: 2 },
                bandwidth: { type: "uint32", id: 3 },
                spreadFactor: { type: "uint32", id: 4 },
                codingRate: { type: "uint32", id: 5 },
                frequencyOffset: { type: "float", id: 6 },
                region: { type: "Config.LoRaConfig.RegionCode", id: 7 },
                hopLimit: { type: "uint32", id: 8 },
                txEnabled: { type: "bool", id: 9 },
                txPower: { type: "int32", id: 10 },
                channelNum: { type: "uint32", id: 11 },
                overrideDutyCycle: { type: "bool", id: 12 },
                sx126xRxBoostedGain: { type: "bool", id: 13 },
                overrideFrequency: { type: "float", id: 14 },
                paFanDisabled: { type: "bool", id: 15 },
                ignoreIncoming: { rule: "repeated", type: "uint32", id: 103 },
                ignoreMqtt: { type: "bool", id: 104 },
                configOkToMqtt: { type: "bool", id: 105 },
                femLnaMode: { type: "uint32", id: 106 }
              },
              nested: {
                RegionCode: {
                  values: {
                    UNSET: 0, US: 1, EU_433: 2, EU_868: 3, CN: 4, JP: 5, ANZ: 6,
                    KR: 7, TW: 8, RU: 9, IN: 10, NZ_865: 11, TH: 12, LORA_24: 13,
                    UA_433: 14, UA_868: 15, MY_433: 16, MY_919: 17, SG_923: 18
                  }
                },
                ModemPreset: {
                  values: {
                    LONG_FAST: 0, LONG_SLOW: 1, VERY_LONG_SLOW: 2,
                    MEDIUM_SLOW: 3, MEDIUM_FAST: 4, SHORT_SLOW: 5, SHORT_FAST: 6,
                    LONG_MODERATE: 7, SHORT_TURBO: 8, LONG_TURBO: 9
                  }
                }
              }
            },

            BluetoothConfig: {
              fields: {
                enabled: { type: "bool", id: 1 },
                mode: { type: "uint32", id: 2 },
                fixedPin: { type: "uint32", id: 3 }
              }
            },

            SecurityConfig: {
              fields: {
                publicKey: { type: "bytes", id: 1 },
                privateKey: { type: "bytes", id: 2 },
                adminKey: { rule: "repeated", type: "bytes", id: 3 },
                isManaged: { type: "bool", id: 4 },
                serialEnabled: { type: "bool", id: 5 },
                debugLogApiEnabled: { type: "bool", id: 6 },
                adminChannelEnabled: { type: "bool", id: 8 }
              }
            }
          }
        },

        // ---- ModuleConfig ----
        ModuleConfig: {
          nested: {
            MapReportSettings: {
              fields: {
                publishIntervalSecs: { type: "uint32", id: 1 },
                positionPrecision: { type: "uint32", id: 2 },
                shouldReportLocation: { type: "bool", id: 3 }
              }
            },

            MQTTConfig: {
              fields: {
                enabled: { type: "bool", id: 1 },
                address: { type: "string", id: 2 },
                username: { type: "string", id: 3 },
                password: { type: "string", id: 4 },
                encryptionEnabled: { type: "bool", id: 5 },
                jsonEnabled: { type: "bool", id: 6 },
                tlsEnabled: { type: "bool", id: 7 },
                root: { type: "string", id: 8 },
                proxyToClientEnabled: { type: "bool", id: 9 },
                mapReportingEnabled: { type: "bool", id: 10 },
                mapReportSettings: { type: "ModuleConfig.MapReportSettings", id: 11 }
              }
            },

            TelemetryConfig: {
              fields: {
                deviceUpdateInterval: { type: "uint32", id: 1 },
                environmentUpdateInterval: { type: "uint32", id: 2 },
                environmentMeasurementEnabled: { type: "bool", id: 3 },
                environmentScreenEnabled: { type: "bool", id: 4 },
                environmentDisplayFahrenheit: { type: "bool", id: 5 },
                airQualityEnabled: { type: "bool", id: 6 },
                airQualityInterval: { type: "uint32", id: 7 },
                powerMeasurementEnabled: { type: "bool", id: 8 },
                powerUpdateInterval: { type: "uint32", id: 9 },
                powerScreenEnabled: { type: "bool", id: 10 },
                deviceTelemetryEnabled: { type: "bool", id: 14 }
              }
            },

            SerialConfig: {
              fields: {
                enabled: { type: "bool", id: 1 },
                echo: { type: "bool", id: 2 },
                rxd: { type: "uint32", id: 3 },
                txd: { type: "uint32", id: 4 },
                baud: { type: "uint32", id: 5 },
                timeout: { type: "uint32", id: 6 },
                mode: { type: "uint32", id: 7 }
              }
            },

            ExternalNotificationConfig: {
              fields: {
                enabled: { type: "bool", id: 1 },
                outputMs: { type: "uint32", id: 2 },
                output: { type: "uint32", id: 3 },
                active: { type: "bool", id: 4 },
                alertMessage: { type: "bool", id: 5 },
                alertBell: { type: "bool", id: 6 },
                usePwm: { type: "bool", id: 7 }
              }
            },

            StoreForwardConfig: {
              fields: {
                enabled: { type: "bool", id: 1 },
                heartbeat: { type: "bool", id: 2 },
                records: { type: "uint32", id: 3 },
                historyReturnMax: { type: "uint32", id: 4 },
                historyReturnWindow: { type: "uint32", id: 5 },
                isServer: { type: "bool", id: 6 }
              }
            },

            RangeTestConfig: {
              fields: {
                enabled: { type: "bool", id: 1 },
                sender: { type: "uint32", id: 2 },
                save: { type: "bool", id: 3 }
              }
            },

            CannedMessageConfig: {
              fields: {
                rotary1Enabled: { type: "bool", id: 1 },
                enabled: { type: "bool", id: 9 },
                sendBell: { type: "bool", id: 11 }
              }
            },

            AudioConfig: {
              fields: {
                codec2Enabled: { type: "bool", id: 1 }
              }
            },

            RemoteHardwareConfig: {
              fields: {
                enabled: { type: "bool", id: 1 },
                allowUndefinedPinAccess: { type: "bool", id: 2 }
              }
            },

            NeighborInfoConfig: {
              fields: {
                enabled: { type: "bool", id: 1 },
                updateInterval: { type: "uint32", id: 2 },
                transmitOverLora: { type: "bool", id: 3 }
              }
            },

            AmbientLightingConfig: {
              fields: {
                ledState: { type: "bool", id: 1 },
                current: { type: "uint32", id: 2 },
                red: { type: "uint32", id: 3 },
                green: { type: "uint32", id: 4 },
                blue: { type: "uint32", id: 5 }
              }
            },

            DetectionSensorConfig: {
              fields: {
                enabled: { type: "bool", id: 1 },
                minimumBroadcastSecs: { type: "uint32", id: 2 },
                stateBroadcastSecs: { type: "uint32", id: 3 },
                sendBell: { type: "bool", id: 4 },
                name: { type: "string", id: 5 },
                monitorPin: { type: "uint32", id: 6 }
              }
            },

            PaxcounterConfig: {
              fields: {
                enabled: { type: "bool", id: 1 },
                paxcounterUpdateInterval: { type: "uint32", id: 2 }
              }
            },

            StatusMessageConfig: {
              fields: {
                nodeStatus: { type: "string", id: 1 }
              }
            },

            TrafficManagementConfig: {
              fields: {
                enabled: { type: "bool", id: 1 }
              }
            },

            TAKConfig: {
              fields: {
                team: { type: "uint32", id: 1 },
                role: { type: "uint32", id: 2 }
              }
            }
          }
        },

        // ---- LocalConfig ----
        LocalConfig: {
          fields: {
            device: { type: "Config.DeviceConfig", id: 1 },
            position: { type: "Config.PositionConfig", id: 2 },
            power: { type: "Config.PowerConfig", id: 3 },
            network: { type: "Config.NetworkConfig", id: 4 },
            display: { type: "Config.DisplayConfig", id: 5 },
            lora: { type: "Config.LoRaConfig", id: 6 },
            bluetooth: { type: "Config.BluetoothConfig", id: 7 },
            version: { type: "uint32", id: 8 },
            security: { type: "Config.SecurityConfig", id: 9 }
          }
        },

        // ---- LocalModuleConfig ----
        LocalModuleConfig: {
          fields: {
            mqtt: { type: "ModuleConfig.MQTTConfig", id: 1 },
            serial: { type: "ModuleConfig.SerialConfig", id: 2 },
            externalNotification: { type: "ModuleConfig.ExternalNotificationConfig", id: 3 },
            storeForward: { type: "ModuleConfig.StoreForwardConfig", id: 4 },
            rangeTest: { type: "ModuleConfig.RangeTestConfig", id: 5 },
            telemetry: { type: "ModuleConfig.TelemetryConfig", id: 6 },
            cannedMessage: { type: "ModuleConfig.CannedMessageConfig", id: 7 },
            audio: { type: "ModuleConfig.AudioConfig", id: 9 },
            remoteHardware: { type: "ModuleConfig.RemoteHardwareConfig", id: 10 },
            neighborInfo: { type: "ModuleConfig.NeighborInfoConfig", id: 11 },
            ambientLighting: { type: "ModuleConfig.AmbientLightingConfig", id: 12 },
            detectionSensor: { type: "ModuleConfig.DetectionSensorConfig", id: 13 },
            paxcounter: { type: "ModuleConfig.PaxcounterConfig", id: 14 },
            statusmessage: { type: "ModuleConfig.StatusMessageConfig", id: 15 },
            trafficManagement: { type: "ModuleConfig.TrafficManagementConfig", id: 16 },
            tak: { type: "ModuleConfig.TAKConfig", id: 17 },
            version: { type: "uint32", id: 8 }
          }
        },

        // ---- ChannelFile (from deviceonly.proto) ----
        ChannelFile: {
          fields: {
            channels: { rule: "repeated", type: "Channel", id: 1 },
            version: { type: "uint32", id: 2 }
          }
        },

        // ---- User (minimal, from mesh.proto) ----
        User: {
          fields: {
            id: { type: "string", id: 1 },
            longName: { type: "string", id: 2 },
            shortName: { type: "string", id: 3 },
            hwModel: { type: "uint32", id: 5 },
            isLicensed: { type: "bool", id: 6 },
            role: { type: "uint32", id: 7 },
            publicKey: { type: "bytes", id: 8 }
          }
        },

        // ---- DeviceProfile (the main Android export format from clientonly.proto) ----
        DeviceProfile: {
          fields: {
            longName: { type: "string", id: 1 },
            shortName: { type: "string", id: 2 },
            channelUrl: { type: "string", id: 3 },
            config: { type: "LocalConfig", id: 4 },
            moduleConfig: { type: "LocalModuleConfig", id: 5 },
            fixedPosition: { type: "Position", id: 6 },
            ringtone: { type: "string", id: 7 },
            cannedMessages: { type: "string", id: 8 }
          }
        },

        // ---- BackupPreferences (from deviceonly.proto, used by some exports) ----
        BackupPreferences: {
          fields: {
            version: { type: "uint32", id: 1 },
            timestamp: { type: "fixed32", id: 2 },
            config: { type: "LocalConfig", id: 3 },
            moduleConfig: { type: "LocalModuleConfig", id: 4 },
            channels: { type: "ChannelFile", id: 5 },
            owner: { type: "User", id: 6 }
          }
        }

      }
    }
  }
};
