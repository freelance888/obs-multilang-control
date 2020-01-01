# OBS Multi Lang Control
Allow to control multiple instances of OBS for multi language streaming. You need to setup multiple OBS's and specify their streaming parameters and language source inputs.

# Usage
## Install
1. [OBS](https://obsproject.com/)
2. [OBS Websocket Plugin](https://github.com/Palakis/obs-websocket) 

## OBS Configuration
1. Create lang `Profile` and `Scene Collection` in OBS. For example `Ru` and `En`.
2. Set uniq websocket port for each profile `Tools -> WebSocket Server Settings` and enable websocket support.
3. Add sources of original video\audio stream and translation. The name should be `Original VA` and `En Translation`(<lang_code> Translation) respectively

## OBS Multi Lang Control Configuration
1. Open the OBS with required `Profile`
2. Connect to OBS by specifying IP and port
3. Select current language of origin source