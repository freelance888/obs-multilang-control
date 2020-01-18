import codecs
import configparser
import json
import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from string import Template
from typing import List

from atom.containerlist import ContainerList
from atom.dict import Dict
from atom.atom import Atom
from atom.instance import Instance
from atom.scalars import Unicode, Bool, Int, Float
from fbs_runtime.platform import is_mac, is_windows
from obswebsocket import obsws, requests, events

DEFAULT_LANG = "Ru"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4444


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
        ws.call(requests.SetCurrentSceneCollection(profile_name))
    return profile_name


def _current_obs_scene(ws):
    scenes = ws.call(requests.GetSceneList()).datain["scenes"]
    if len(scenes) > 1:
        raise ValueError("Only one `Scene` should be present in OBS")
    if scenes[0]["name"].lower() != "scene":
        raise ValueError("Scene should have name `Scene`")
    return scenes[0]


def _current_obs_stream_settings(ws):
    settings = ws.call(requests.GetStreamSettings())
    return settings.datain


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
    # stream_server_url = Unicode()
    # stream_key = Unicode()
    # stream_settings = Dict(dict(type='rtmp_common', save=True, settings=dict(ser)))
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
        self._populate_data()
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

    def _populate_data(self):
        self.lang_code = _current_obs_lang(self.ws)
        scene = _current_obs_scene(self.ws)
        for source in scene["sources"]:
            if source["name"] == "VA Origin":
                self.origin_source = source
            elif source["name"] == f"TS {self.lang_code} Translation":
                self.trans_source = source
        self.scene_name = scene["name"]

    # settings = _current_obs_stream_settings(self.ws)
    # if settings["type"] == "rtmp_common":
    #     self.stream_key = settings["settings"]["key"]
    #     self.stream_server_url = settings["settings"]["server"]

    def _set_mute(self, source_name, mute):
        self.ws.call(requests.SetMute(source_name, mute))

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

    def __setstate__(self, state):
        self.host = state["host"]
        self.port = state["port"]
        self.origin_volume_level_on_origin = state["origin_volume_level_on_origin"]
        self.origin_volume_level_on_trans = state["origin_volume_level_on_trans"]
        self.trans_volume_level_on_trans = state["trans_volume_level_on_trans"]
        if not self.is_connected and state["is_connected"]:
            self.connect()

    def __getstate__(self):
        return dict(
            host=self.host,
            port=self.port,
            is_connected=self.is_connected,
            origin_volume_level_on_origin=self.origin_volume_level_on_origin,
            origin_volume_level_on_trans=self.origin_volume_level_on_trans,
            trans_volume_level_on_trans=self.trans_volume_level_on_trans,
        )


class Profile(Atom):
    lang_code = Unicode(default=DEFAULT_LANG)
    websocket_port = Int(default=DEFAULT_PORT)

    def __str__(self):
        return f"{self.lang_code}    {self.websocket_port}"


class ObsConfigurationModel(Atom):
    DEFAULT_LANG = DEFAULT_LANG
    obs_studio_config_path = Unicode()
    template_profile_path = Unicode()
    template_scene_path = Unicode()

    profiles = ContainerList(Profile)

    def _set_config_path(self):
        home = Path.home()
        if is_mac():
            self.obs_studio_config_path = str(
                home / "Library/Application Support/obs-studio"
            )
        elif is_windows():
            self.obs_studio_config_path = str(home / "AppData/Roaming/obs-studio")
        logging.debug(f"OBS Studio path config {self.obs_studio_config_path}")

    def update_available_profiles(self):
        if not self.obs_studio_config_path:
            self._set_config_path()
        for path in Path(self.obs_studio_config_path).rglob("*/basic.ini"):
            config = configparser.ConfigParser()
            config.read_file(codecs.open(path, "r", "utf-8-sig"))
            lang_code = config["General"]["Name"]
            try:
                port = int(config["WebsocketAPI"]["ServerPort"])
            except KeyError:
                continue
            if port in self.used_ports:
                continue
            self.profiles.append(Profile(lang_code=lang_code, websocket_port=port))
        logging.debug(f"Profiles updated")
        return self.profiles

    @property
    def used_ports(self):
        return [p.websocket_port for p in self.profiles]

    def _read_config(self, path):
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(path)
        return config

    def _write_config(self, config, path):
        with open(path, "w") as basic_ini:
            config.write(basic_ini, space_around_delimiters=False)

    def _create_profile(self, profile, basic_dir):
        config = self._read_config(Path(self.template_profile_path) / "basic.ini")
        config["General"]["Name"] = profile.lang_code
        config["WebsocketAPI"]["ServerEnabled"] = "true"
        config["WebsocketAPI"]["ServerPort"] = str(profile.websocket_port)

        lang_obs_profile_path = basic_dir / "profiles" / profile.lang_code
        logging.debug(f"Lang obs profile path {lang_obs_profile_path}")
        if not lang_obs_profile_path.exists():
            lang_obs_profile_path.mkdir()
        self._write_config(config, lang_obs_profile_path / "basic.ini")

        shutil.copy(
            Path(self.template_profile_path) / "service.json",
            lang_obs_profile_path / "service.json",
        )

    def _create_scene(self, profile, basic_dir):
        lang_obs_scene_path = basic_dir / "scenes" / "{}.json".format(profile.lang_code)
        logging.debug(f"Lang obs scene path {lang_obs_scene_path}")
        with open(self.template_scene_path, "r") as templ:
            templ = Template(templ.read())
            conf_text = templ.substitute(
                dict(
                    lang_code=profile.lang_code.capitalize(),
                    lang_code_lower=profile.lang_code.lower(),
                )
            )
            with open(lang_obs_scene_path, "w") as f:
                f.write(conf_text)

    def create_profile_and_scene(self, profile: Profile):
        if not self.obs_studio_config_path:
            self._set_config_path()
        if profile.websocket_port in self.used_ports:
            logging.error("Port already used")
            return
        if not profile.lang_code:
            logging.error("No lang code")
            return

        basic_dir = Path(self.obs_studio_config_path) / "basic"
        logging.info(f"Basic dir {basic_dir}")
        for path in basic_dir.rglob("*"):
            if path.name.lower() == profile.lang_code.lower():
                logging.error(f"`{path.name}` is already created")
        self._create_profile(profile, basic_dir)
        self._create_scene(profile, basic_dir)

    def remove_profile_and_scene(self, profile: Profile):
        profile_id = self.profiles.index(profile)
        if profile_id == -1:
            return
        profile = self.profiles.pop(profile_id)
        basic_dir = Path(self.obs_studio_config_path) / "basic"
        profile_dir = basic_dir / "profiles" / profile.lang_code
        if profile_dir.exists():
            rm_tree(profile_dir)
        scene_file = basic_dir / "scenes" / "{}.json".format(profile.lang_code)
        scene_file.unlink()

    def open_obs_instance(self, profile: Profile):
        app_dir = os.getcwd()
        code = profile.lang_code
        if is_mac():
            path = "/Applications/"
            if not Path(path) / "OBS.app":
                raise ValueError("No OBS instance present")
            args = shlex.split(
                f"/usr/bin/open -n -a OBS.app --args --multi --profile {code} --collection {code}"
            )
        elif is_windows():
            path32 = "C:/Program Files (x86)/obs-studio/bin/32bit/"
            path64 = "C:/Program Files/obs-studio/bin/64bit/"
            if Path(path32).exists():
                path = path32
                obs_name = 'obs32'
            elif Path(path64).exists():
                path = path64
                obs_name = 'obs64'
            else:
                raise ValueError("No OBS instance present")
            args = shlex.split(
                f'{obs_name}.exe --multi --profile "{code}" --collection "{code}"', posix=False,
            )

        else:
            logging.error("Not supported platform")
            return
        os.chdir(path)
        logging.info(f"Args for opening: {args}")
        subprocess.Popen(args)
        os.chdir(app_dir)


def rm_tree(pth: Path):
    for child in pth.glob("*"):
        if child.is_file():
            child.unlink()
        else:
            rm_tree(child)
    pth.rmdir()


class ObsManagerModel(Atom):
    ORIGINAL_LANG = "Original"

    current_lang_code = Unicode()
    obs_instances: List[ObsInstanceModel] = ContainerList(default=[ObsInstanceModel()])
    state_path = Unicode()
    status = Unicode()

    def add_obs_instance(self, obs_or_host=None, port=None):
        if isinstance(obs_or_host, ObsInstanceModel):
            obs = obs_or_host
        elif obs_or_host and port:
            obs = ObsInstanceModel(host=obs_or_host.strip(), port=port)
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
        logging.debug(self.status)
        return obs

    def pop_obs_instance(self):
        obs = self.obs_instances.pop()
        obs.disconnect()

    def __getstate__(self):
        return dict(
            current_lang_code=self.current_lang_code,
            obs_instances=[o.__getstate__() for o in self.obs_instances],
        )

    def __setstate__(self, state):
        self.current_lang_code = state["current_lang_code"]
        self.obs_instances.clear()
        for obs_data in state["obs_instances"]:
            obs = ObsInstanceModel()
            obs.__setstate__(obs_data)
            self.add_obs_instance(obs)

    def switch_to_lang(self, next_lang_code):
        if next_lang_code == self.current_lang_code:
            logging.info(f"Already at {next_lang_code}")
            return
        next_obs = None
        for obs in self.obs_instances:
            if next_lang_code == self.ORIGINAL_LANG:
                obs.switch_to_origin()
                continue
            if obs.lang_code == next_lang_code:
                obs.switch_to_origin()
                next_obs = obs
                logging.info(f"OBS {obs.lang_code} was switched to ORIGIN sound")
            elif obs.lang_code == self.current_lang_code:
                obs.switch_to_translation()
                logging.info(f"OBS {obs.lang_code} was switched to TRANSLATION sound")
        self.status = f"Switched from {self.current_lang_code} to {next_lang_code}!"
        logging.debug(self.status)
        self.current_lang_code = next_lang_code
        return next_obs

    def save_state(self):
        with open(self.state_path, "w") as f:
            json.dump(self.__getstate__(), f)

    def restore_state(self):
        with open(self.state_path, "r") as f:
            data = json.load(f)
            self.__setstate__(data)

    def connect_all(self):
        for o in self.obs_instances:
            o.connect()

    def disconnect_all(self):
        for o in self.obs_instances:
            o.disconnect()

    def start_streams(self):
        for o in self.obs_instances:
            o.start_stream()

    def stop_streams(self):
        for o in self.obs_instances:
            o.stop_stream()

    def mute_audios(self):
        for o in self.obs_instances:
            o.mute_audio()

    def unmute_audios(self):
        for o in self.obs_instances:
            o.unmute_audio()
