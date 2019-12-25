import logging

from atom.dict import Dict
from atom.atom import Atom
from atom.instance import Instance
from atom.list import List
from atom.scalars import Unicode, Float
from obswebsocket import obsws, requests

HOST = "0.0.0.0"


def on_event(msg):
    print(msg)


def _create_connection(host, port, password=None):
    ws = obsws(host, port, password)
    ws.register(on_event)
    ws.connect()
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

    @classmethod
    def create(cls, host=HOST, port=4444):
        ws = _create_connection(host, port)
        lang_code = _current_obs_lang(ws)
        scene = _current_obs_scene(ws)
        origin_source = trans_source = None
        for source in scene["sources"]:
            if source["name"] == "Origin VA":
                origin_source = source
            elif source["name"] == f"{lang_code} Translation":
                trans_source = source

        return cls(
            ws=ws,
            lang_code=lang_code,
            scene_name=scene["name"],
            origin_source=origin_source,
            trans_source=trans_source,
        )

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


class LanguageSwitcherModel(Atom):
    current_lang_code = Unicode()
    obs_instances = List(ObsInstanceModel)

    @classmethod
    def create(cls, *obs_instances):
        instance = cls(current_lang_code="", obs_instances=list(obs_instances))
        instance.switch_to_lang("Ru")
        return instance

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
