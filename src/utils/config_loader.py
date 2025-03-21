import yaml
import re
import os


class ConfigLoader:
    REF_PATTERN = re.compile(r"\$\{([^:}]+):([^}]+)\}")

    def __init__(self, config_path: str):
        self.config_path = config_path
        with open(config_path, "r") as file:
            self.config = yaml.safe_load(file)
        self._resolve_references(self.config, os.path.dirname(config_path))

    def _resolve_references(self, data, base_dir):
        if isinstance(data, dict):
            for k, v in data.items():
                data[k] = self._resolve_references(v, base_dir)
        elif isinstance(data, list):
            data = [self._resolve_references(i, base_dir) for i in data]
        elif isinstance(data, str):
            match = self.REF_PATTERN.search(data)
            if match:
                ref_file, ref_key = match.groups()
                # ref_path = os.path.join(base_dir, ref_file)

                if ref_file == "env":
                    ref_value = os.getenv(ref_key)
                else:
                    with open(ref_file, "r") as f:
                        ref_config = yaml.safe_load(f)
                    ref_value = self._get_from_dict(ref_config, ref_key)

                # 完整引用（若整個字串就是引用）
                if data.strip() == match.group(0):
                    return ref_value
                else:  # 部分引用（字串內嵌入引用）
                    return data.replace(match.group(0), str(ref_value))
        return data

    def _get_from_dict(self, data_dict, key_path):
        keys = key_path.split(".")
        for key in keys:
            data_dict = data_dict.get(key)
            if data_dict is None:
                return None
        return data_dict

    def get(self, key, default=None):
        keys = key.split(".")
        val = self.config
        for k in keys:
            val = val.get(k)
            if val is None:
                return default
        return val
