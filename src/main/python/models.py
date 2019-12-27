import logging

from atom.containerlist import ContainerList
from atom.dict import Dict
from atom.atom import Atom
from atom.instance import Instance
from atom.scalars import Unicode, Bool, Int
from obswebsocket import obsws, requests

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 4444
BASE_LANG = "Ru"


def on_event(msg):
    print(msg)


def _create_connection(host, port, password=None):
    ws = obsws(host, port, password)
    ws.register(on_event)
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

    def refresh_sources(self):
        self.ws.call(
            requests.SetSourceSettings(self.origin_source["name"], self.origin_source)
        )
        self.ws.call(
            requests.SetSourceSettings(self.trans_source["name"], self.trans_source)
        )

    def switch_to_origin(self):
        origin_res = self.ws.call(requests.SetVolume(self.origin_source["name"], 1.0))
        self.origin_source["volume"] = origin_res.dataout["volume"]
        trans_res = self.ws.call(requests.SetVolume(self.trans_source["name"], 0.0))
        self.trans_source["volume"] = trans_res.dataout["volume"]

    def switch_to_translation(self):
        origin_res = self.ws.call(requests.SetVolume(self.origin_source["name"], 0.20))
        self.origin_source["volume"] = origin_res.dataout["volume"]
        trans_res = self.ws.call(requests.SetVolume(self.trans_source["name"], 1.0))
        self.trans_source["volume"] = trans_res.dataout["volume"]

    def connect(self, host=None, port=None):
        if self.is_connected:
            return self.is_connected
        if host and port:
            self.host = host
            self.port = port
        ws = _create_connection(self.host, self.port)
        if ws is None:
            return self.is_connected
        self.ws = ws
        self.lang_code = _current_obs_lang(self.ws)
        scene = _current_obs_scene(self.ws)
        for source in scene["sources"]:
            if source["name"] == "Origin VA":
                self.origin_source = source
            elif source["name"] == f"{self.lang_code} Translation":
                self.trans_source = source
        self.scene_name = scene["name"]
        self.is_connected = True
        return self.is_connected

    def disconnect(self):
        if not self.is_connected:
            return self.is_connected
        self.ws.disconnect()
        self.is_connected = False
        return self.is_connected


class ObsManagerModel(Atom):
    current_lang_code = Unicode()
    obs_instances = ContainerList(default=[ObsInstanceModel()])

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
            logging.info(f"OBS {obs.port} already added")
            return obs
        self.obs_instances.append(obs)
        return obs

    def __getitem__(self, item: str):
        for obs in self.obs_instances:
            if item == obs.port:
                return obs
        raise KeyError(f"{item} isn't present in obs instances")

    def switch_to_lang(self, next_lang_code):
        if next_lang_code == self.current_lang_code:
            logging.info(f"Already at {next_lang_code}")
            return
        for obs in self.obs_instances:
            if obs.lang_code == next_lang_code:
                obs.switch_to_origin()
                logging.info(f"OBS {obs.lang_code} was switched to ORIGIN sound")
            elif obs.lang_code == self.current_lang_code:
                obs.switch_to_translation()
                logging.info(f"OBS {obs.lang_code} was switched to TRANSLATION sound")
        self.current_lang_code = next_lang_code
