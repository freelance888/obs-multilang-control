import logging
from copy import copy

import trafaret as t
from atom.atom import Atom
from atom.dict import Dict
from atom.instance import Instance
from atom.scalars import Unicode, Int, Bool, Float
from obswebsocket import obsws, requests, events

from settings import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_YOUTUBE_STREAM_URL,
)
from utils import is_open


def _create_connection(host, port, password=None):
    host = t.IPv4.check(host)
    if not is_open(host, port):
        logging.error(f"Address {host}:{port} not reachable")
        return None
    ws = obsws(host, port, password)
    try:
        ws.connect()
    except Exception as e:
        logging.exception(e)
        return None
    return ws


def _current_obs_stream_settings(ws):
    settings = ws.call(requests.GetStreamSettings())
    return settings.datain


def _current_obs_scene(ws):
    scenes = ws.call(requests.GetSceneList()).datain["scenes"]
    if scenes[0]["name"].lower() != "scene":
        raise ValueError("Scene should have name `Scene`")
    return scenes[0]


def _current_obs_lang(ws):
    profile_name = ws.call(requests.GetCurrentProfile()).datain["profile-name"]
    scene_source_name = ws.call(requests.GetCurrentSceneCollection()).datain["sc-name"]
    if profile_name != scene_source_name:
        ws.call(requests.SetCurrentSceneCollection(profile_name))
    return profile_name


class ObsInstanceModel(Atom):
    ws: obsws = Instance(obsws)
    lang_code = Unicode()
    scene_name = Unicode()
    origin_source = Dict()
    trans_source = Dict()
    host = Unicode(default=DEFAULT_HOST)
    port = Int(default=DEFAULT_PORT)
    is_connected = Bool()
    is_origin_audio = Bool()
    switch_triggered = Bool()

    is_stream_started = Bool()
    is_audio_muted = Bool()
    stream_settings = Dict(
        default=dict(
            bwtest=False,
            type="rtmp_custom",
            save=True,
            use_auth=False,
            key="",
            server=DEFAULT_YOUTUBE_STREAM_URL,
        )
    )
    origin_volume_level_on_origin = Float(1.0)

    origin_volume_level_on_trans = Float(0.20)
    trans_volume_level_on_trans = Float(1.0)

    def refresh_sources(self):
        self.ws.call(
            requests.SetSourceSettings(self.origin_source["name"], self.origin_source)
        )
        self.ws.call(
            requests.SetSourceSettings(self.trans_source["name"], self.trans_source)
        )

    def _change_volume(self, name, volume):
        self.switch_triggered = True
        self.ws.call(requests.SetVolume(name, volume))

    def switch_to_origin(self):
        self._change_volume(
            self.origin_source["name"], self.origin_volume_level_on_origin
        )
        self._change_volume(self.trans_source["name"], 0.0)
        self.is_origin_audio = True

    def switch_to_translation(self):
        self._change_volume(
            self.origin_source["name"], self.origin_volume_level_on_trans
        )
        self._change_volume(self.trans_source["name"], self.trans_volume_level_on_trans)
        self.is_origin_audio = False

    def start_stream(self):
        self.ws.call(requests.StartStreaming())

    def stop_stream(self):
        self.ws.call(requests.StopStreaming())

    def connect(self, host=None, port=None):
        if self.is_connected:
            return True
        if host and port:
            self.host = host
            self.port = port
        ws = _create_connection(self.host, self.port)
        if ws is None:
            return False
        self.ws = ws
        self._receive_data_from_obs()
        self._register_callbacks()
        self.is_connected = True
        return self.is_connected

    def _register_callbacks(self):
        def handle_volume(e: events.SourceVolumeChanged):
            """Save volume level changed from OBS"""
            if self.switch_triggered:
                self.switch_triggered = False
                return
            if e.getSourcename() == self.origin_source["name"]:
                if self.is_origin_audio:
                    self.origin_volume_level_on_origin = e.getVolume()
                else:
                    self.origin_volume_level_on_trans = e.getVolume()
            elif e.getSourcename() == self.trans_source["name"]:
                if not self.is_origin_audio:
                    self.trans_volume_level_on_trans = e.getVolume()

        def handle_streaming_status(e: events.StreamStatus):
            if isinstance(e, events.StreamStopped):
                self.is_stream_started = False
                return
            self.is_stream_started = e.getStreaming()

        def handle_exiting(e: events.Exiting):
            self.is_connected = False
            self.is_stream_started = False

        self.ws.register(handle_volume, events.SourceVolumeChanged)
        self.ws.register(handle_streaming_status, events.StreamStatus)
        self.ws.register(handle_streaming_status, events.StreamStopped)
        self.ws.register(handle_exiting, events.Exiting)

    def _receive_data_from_obs(self):
        self.lang_code = _current_obs_lang(self.ws)
        scene = _current_obs_scene(self.ws)
        for source in scene["sources"]:
            if source["name"] == "VA Origin":
                self.origin_source = source
            elif source["name"] == f"TS {self.lang_code} Translation":
                self.trans_source = source
        self.scene_name = scene["name"]

        settings = _current_obs_stream_settings(self.ws)
        if settings["settings"]:
            self.stream_settings = settings["settings"]

    def _set_mute(self, source_name, mute):
        self.ws.call(requests.SetMute(source_name, mute))

    def mute_translation_audio(self):
        self._set_mute(self.trans_source["name"], True)
        self.is_audio_muted = True

    def mute_audio(self):
        self._set_mute(self.origin_source["name"], True)
        self._set_mute(self.trans_source["name"], True)
        self.is_audio_muted = True

    def unmute_audio(self):
        self._set_mute(self.origin_source["name"], False)
        self._set_mute(self.trans_source["name"], False)
        self.is_audio_muted = False

    def disconnect(self):
        if not self.is_connected:
            return self.is_connected
        self.ws.disconnect()
        self.is_connected = False
        return self.is_connected

    def populate_steam_settings_to_obs(self):
        settings = copy(self.stream_settings)
        settings["key"] = settings["key"].strip()
        settings["server"] = settings["server"].strip()
        type = self.stream_settings.get("type")
        if type is None:
            if "rtmp.youtube.com" in settings["server"]:
                type = "rtmp_common"
        result = self.ws.call(
            requests.SetStreamSettings(type=type, save=True, settings=settings,)
        )
        return result.status

    def __setstate__(self, state):
        self.host = state["host"]
        self.port = state["port"]
        self.origin_volume_level_on_origin = state["origin_volume_level_on_origin"]
        self.origin_volume_level_on_trans = state["origin_volume_level_on_trans"]
        self.trans_volume_level_on_trans = state["trans_volume_level_on_trans"]

    def __getstate__(self):
        return dict(
            host=self.host,
            port=self.port,
            is_connected=self.is_connected,
            origin_volume_level_on_origin=self.origin_volume_level_on_origin,
            origin_volume_level_on_trans=self.origin_volume_level_on_trans,
            trans_volume_level_on_trans=self.trans_volume_level_on_trans,
        )
