import json
import logging

from atom.containerlist import ContainerList
from atom.dict import Dict
from atom.atom import Atom
from atom.instance import Instance
from atom.scalars import Unicode, Bool, Int, Float
from obswebsocket import obsws, requests, events

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 4444
BASE_LANG = "Ru"


def _create_connection(host, port, password=None):
    ws = obsws(host, port, password)
    try:
        ws.connect()
    except Exception as e:
        logging.exception(e)
        return None
    return ws


def _current_obs_lang(ws):
    profile_name = ws.call(requests.GetCurrentProfile()).datain["profile-name"]
    scene_source_name = ws.call(requests.GetCurrentSceneCollection()).datain["sc-name"]
    if profile_name != scene_source_name:
        raise ValueError("`Profile` name should be exactly same as `Scene collection`")
    return profile_name


def _current_obs_scene(ws):
    scenes = ws.call(requests.GetSceneList()).datain["scenes"]
    if len(scenes) > 1:
        raise ValueError("Only one `Scene` should be present in OBS")
    if scenes[0]["name"].lower() != "scene":
        raise ValueError("Scene should have name `Scene`")
    return scenes[0]


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

    def connect(self, host=None, port=None):
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

        if self.is_connected:
            return True
        if host and port:
            self.host = host
            self.port = port
        ws = _create_connection(self.host, self.port)
        if ws is None:
            return False
        ws.register(handle_volume, events.SourceVolumeChanged)
        self.ws = ws
        self._populate_data()
        self.is_connected = True
        return self.is_connected

    def _populate_data(self):
        self.lang_code = _current_obs_lang(self.ws)
        scene = _current_obs_scene(self.ws)
        for source in scene["sources"]:
            if source["name"] == "Origin VA":
                self.origin_source = source
            elif source["name"] == f"{self.lang_code} Translation":
                self.trans_source = source
        self.scene_name = scene["name"]

    def disconnect(self):
        if not self.is_connected:
            return self.is_connected
        self.ws.disconnect()
        self.is_connected = False
        return self.is_connected


class ObsManagerModel(Atom):
    current_lang_code = Unicode()
    obs_instances = ContainerList(default=[ObsInstanceModel()])
    state_path = Unicode()
    status = Unicode()

    def add_obs_instance(self, obs_or_host=None, port=None):
        if isinstance(obs_or_host, ObsInstanceModel):
            obs = obs_or_host
        elif obs_or_host and port:
            obs = ObsInstanceModel(host=obs_or_host, port=port)
        else:
            obs = ObsInstanceModel()
        if obs.port != DEFAULT_PORT and obs.port in [
            o.port for o in self.obs_instances
        ]:
            self.status = f"OBS {obs.port} already added"
            logging.info(self.status)
            return obs
        self.obs_instances.append(obs)
        self.status = f"OBS configuration with address {obs.host}:{obs.port} created!"
        return obs

    def remove_obs_instance(self, obs):
        for i, lang_code in enumerate(o.lang_code for o in self.obs_instances):
            if obs.lang_code == lang_code:
                obs = self.obs_instances.pop(i)
                break
        obs.disconnect()

    def __getitem__(self, item: str):
        for obs in self.obs_instances:
            if item == obs.port:
                return obs
        raise KeyError(f"{item} isn't present in obs instances")

    def switch_to_lang(self, next_lang_code):
        if next_lang_code == self.current_lang_code:
            logging.info(f"Already at {next_lang_code}")
            return
        next_obs = None
        for obs in self.obs_instances:
            if obs.lang_code == next_lang_code:
                obs.switch_to_origin()
                next_obs = obs
                logging.info(f"OBS {obs.lang_code} was switched to ORIGIN sound")
            elif obs.lang_code == self.current_lang_code:
                obs.switch_to_translation()
                logging.info(f"OBS {obs.lang_code} was switched to TRANSLATION sound")
        self.status = f"Switched from {self.current_lang_code} to {next_lang_code}!"
        self.current_lang_code = next_lang_code
        return next_obs

    def save_state(self):
        data = dict(
            current_lang_code=self.current_lang_code,
            obs_instances=[
                dict(host=o.host, port=o.port, is_connected=o.is_connected)
                for o in self.obs_instances
            ],
        )
        with open(self.state_path, "w") as f:
            json.dump(data, f)
        self.status = "State saved!"

    def restore_state(self):
        with open(self.state_path, "r") as f:
            data = json.load(f)

        self.current_lang_code = data["current_lang_code"]
        self.obs_instances.clear()
        for con in data["obs_instances"]:
            obs = self.add_obs_instance(con["host"], con["port"])
            if con["is_connected"]:
                obs.connect()

    def connect_all(self):
        for o in self.obs_instances:
            o.connect()

    def disconnect_all(self):
        for o in self.obs_instances:
            o.connect()
