import json
import logging
from typing import List

from atom.atom import Atom
from atom.containerlist import ContainerList
from atom.scalars import Unicode

from models.obs_connection import ObsInstanceModel
from settings import DEFAULT_PORT


class ObsManagerModel(Atom):
    ORIGINAL_ONLY = "Original only"
    TRANSLATION_ONLY = "Translation only"

    current_lang_code = Unicode()
    obs_instances: List[ObsInstanceModel] = ContainerList(default=[ObsInstanceModel()])
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
        logging.debug(self.status)
        return obs

    def remove_obs_instance(self, obs):
        obs.disconnect()
        self.obs_instances.remove(obs)

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

        next_obs = None
        for obs in self.obs_instances:
            if next_lang_code == self.ORIGINAL_ONLY or (
                self.current_lang_code == self.TRANSLATION_ONLY
                and obs.lang_code != next_lang_code
            ):
                obs.switch_to_origin()
                continue
            elif (
                self.current_lang_code == self.ORIGINAL_ONLY
                and obs.lang_code != next_lang_code
            ) or next_lang_code == self.TRANSLATION_ONLY:
                obs.switch_to_translation()
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

    def mute_translation_audios(self):
        for o in self.obs_instances:
            o.mute_translation_audio()

    def mute_audios(self):
        for o in self.obs_instances:
            o.mute_audio()

    def unmute_audios(self):
        for o in self.obs_instances:
            o.unmute_audio()

    def populate_streams_settings(self):
        for o in self.obs_instances:
            if o.is_connected:
                o.populate_steam_settings_to_obs()
