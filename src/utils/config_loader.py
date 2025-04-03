import yaml
import re
import os
import json


class ConfigLoader:
    REF_PATTERN = re.compile(r"\$\{([^:}]+):([^}]+)\}")

    def __init__(self, config_path: str):
        self.config_path = config_path
        file_extension = os.path.splitext(config_path)[1].lower()

        try:  # Add try block for file opening
            with open(config_path, "r") as file:
                # --- Choose loader based on extension ---
                if file_extension == ".yaml" or file_extension == ".yml":
                    self.config = yaml.safe_load(file)
                elif file_extension == ".json":
                    self.config = json.load(file)  # <-- Use json.load for .json files
                else:
                    # Optionally support other formats or raise error
                    raise ValueError(
                        f"Unsupported configuration file format: {file_extension}"
                    )
                # --- End Loader Choice ---

        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise ValueError(
                f"Error parsing configuration file {config_path}: {e}"
            ) from e
        except Exception as e:  # Catch other potential errors like permission issues
            raise IOError(f"Error reading configuration file {config_path}: {e}") from e

        # Resolve references after loading
        if self.config is not None:  # Check if loading was successful
            self._resolve_references(self.config, os.path.dirname(config_path))
        else:
            # Handle case where file is empty or loading failed silently (shouldn't happen with exceptions)
            self.config = {}  # Assign empty dict if loading resulted in None

    def _resolve_references(self, data, base_dir):
        if isinstance(data, dict):
            # Use items() for safe iteration during potential modification
            items = list(data.items())
            for k, v in items:
                resolved_v = self._resolve_references(v, base_dir)
                if resolved_v is not v:  # Update only if resolution changed something
                    data[k] = resolved_v
        elif isinstance(data, list):
            # Create a new list with resolved items
            resolved_list = [self._resolve_references(i, base_dir) for i in data]
            # Check if any item actually changed before creating new list instance? Optional optimization.
            return resolved_list  # Return the new list
        elif isinstance(data, str):
            # Keep resolving until no more patterns are found in the string
            resolved_string = data
            while True:
                match = self.REF_PATTERN.search(resolved_string)
                if not match:
                    break  # No more patterns found

                ref_type, ref_key = match.groups()  # Changed ref_file to ref_type

                # Determine value based on reference type
                ref_value = None
                if ref_type == "env":
                    ref_value = os.getenv(ref_key)
                    if ref_value is None:
                        print(
                            f"Warning: Environment variable '{ref_key}' not found, replacing with empty string."
                        )
                        ref_value = ""  # Replace with empty string if not found
                # --- Removed file reference logic for simplicity ---
                # --- Add other reference types here if needed (e.g., ${config:other.key}) ---
                else:
                    print(
                        f"Warning: Unsupported reference type '{ref_type}' in '{resolved_string}'. Skipping."
                    )
                    # Skip this match and continue searching the rest of the string
                    # Need careful handling here to avoid infinite loops if replacement fails
                    # For now, just break the loop if type is unsupported
                    break

                # Perform replacement
                # Ensure ref_value is string for replacement
                ref_value_str = str(ref_value)
                resolved_string = resolved_string.replace(match.group(0), ref_value_str)

            return resolved_string  # Return the fully resolved string

        # Return data unchanged if not dict, list, or string
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
