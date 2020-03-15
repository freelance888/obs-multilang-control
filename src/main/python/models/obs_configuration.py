import codecs
import configparser
import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from string import Template

from atom.atom import Atom
from atom.containerlist import ContainerList
from atom.scalars import Unicode, Int
from fbs_runtime.platform import is_mac, is_windows

from settings import DEFAULT_LANG, DEFAULT_PORT
from utils import rm_tree


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
        config.read_file(codecs.open(path, "r", "utf-8-sig"))
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
        shutil.copy(
            Path(self.template_profile_path) / "streamEncoder.json",
            lang_obs_profile_path / "streamEncoder.json",
        )

    def _create_global_conf(self, basic_dir):
        config = self._read_config(basic_dir / "global.ini")
        config["BasicWindow"][
            "DockState"
        ] = "AAAA/wAAAAD9AAAAAwAAAAAAAADkAAABEPwCAAAAAfsAAAASAG0AaQB4AGUAcgBEAG8AYwBrAQAAABUAAAEQAAAA+QD///8AAAABAAAAqAAAARD8AgAAAAL7AAAAFgBzAG8AdQByAGMAZQBzAEQAbwBjAGsBAAAAFQAAAH4AAAB+AP////sAAAAYAGMAbwBuAHQAcgBvAGwAcwBEAG8AYwBrAQAAAJcAAACOAAAAjgD///8AAAADAAADVAAAAJf8AQAAAAP7AAAAFABzAGMAZQBuAGUAcwBEAG8AYwBrAAAAAAAAAAHRAAAAqAD////7AAAAHgB0AHIAYQBuAHMAaQB0AGkAbwBuAHMARABvAGMAawAAAAJAAAAAhgAAAIIA////+wAAABIAcwB0AGEAdABzAEQAbwBjAGsCAAAE6QAAAH8AAAK8AAAAyAAAAJYAAAEQAAAABAAAAAQAAAAIAAAACPwAAAAA"
        config["BasicWindow"]["VerticalVolControl"] = "true"
        config["BasicWindow"][
            "geometry"
        ] = "AdnQywACAAAAAAUqAAAAJQAAB2MAAAGJAAAFMgAAAEQAAAdbAAABgQAAAAAAAAAAB4A="
        self._write_config(config, basic_dir / "global.ini")

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
        self._create_global_conf(Path(self.obs_studio_config_path))
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
                obs_name = "obs32"
            elif Path(path64).exists():
                path = path64
                obs_name = "obs64"
            else:
                raise ValueError("No OBS instance present")
            args = shlex.split(
                f'{obs_name}.exe --multi --profile "{code}" --collection "{code}"',
                posix=False,
            )

        else:
            logging.error("Not supported platform")
            return
        os.chdir(path)
        logging.info(f"Args for opening: {args}")
        subprocess.Popen(args)
        os.chdir(app_dir)
