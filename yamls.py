import os
from chart import HelmChart
from ruamel.yaml import YAML

def get_yaml_files(base_appspec_folder):
    """
    Recursively finds all YAML files in the specified folder.

    Args:
        base_appspec_folder (str): The base folder to search for YAML files.

    Returns:
        list: A list of paths to the found YAML files.
    """
    yaml_files = []
    for root, dirs, files in os.walk(base_appspec_folder):
        for file in files:
            if file.endswith('.yaml') or file.endswith('.yml'):
                yaml_files.append(os.path.join(root, file))
    return yaml_files

def extract_values(yaml_file):
    """
    Extracts Helm chart related values from a YAML file.

    Args:
        yaml_file (str): The path to the YAML file.

    Returns:
        HelmChart: An instance of HelmChart with extracted values, or None if extraction fails.
    """
    addon_chart_repository_namespace = None
    yaml = YAML()
    with open(yaml_file, 'r') as file:
        print(f"Extracting values from {yaml_file}")
        content = yaml.load(file)
        try:
            addon_chart = content['spec']['generators'][0]['merge']['generators'][0]['clusters']['values']['addonChart']
            addon_chart_version = content['spec']['generators'][0]['merge']['generators'][0]['clusters']['values']['addonChartVersion']
            addon_chart_repository = content['spec']['generators'][0]['merge']['generators'][0]['clusters']['values']['addonChartRepository']
            
            if 'addonChartRepositoryNamespace' in content['spec']['generators'][0]['merge']['generators'][0]['clusters']['values']:
                addon_chart_repository_namespace = content['spec']['generators'][0]['merge']['generators'][0]['clusters']['values']['addonChartRepositoryNamespace']
            else:
                addon_chart_repository_namespace = ""
            if 'addonChartReleaseName' in content['spec']['generators'][0]['merge']['generators'][0]['clusters']['values']:
                addon_chart_release_name = content['spec']['generators'][0]['merge']['generators'][0]['clusters']['values']['addonChartReleaseName']
            else:
                addon_chart_release_name = ""

            return HelmChart(addon_chart, addon_chart_version, addon_chart_repository, addon_chart_repository_namespace, addon_chart_release_name)
        except (KeyError, TypeError):
            print(f"Unable to extract values from {yaml_file}")
            return None

def copy_and_update_yaml(yaml_file, new_destination, base_appspec_folder, new_version, private_ecr_url):
    """
    Copies a YAML file to a new destination and updates specific values.

    Args:
        yaml_file (str): The path to the original YAML file.
        new_destination (str): The destination folder to copy the updated YAML file to.
        base_appspec_folder (str): The base folder for calculating relative paths.
        new_version (str): The new version to set for the addonChartVersion in the YAML file.
        private_ecr_url (str): The new repository URL to set for the addonChartRepository in the YAML file.
    """
    new_file_path = os.path.join(new_destination, os.path.relpath(yaml_file, base_appspec_folder))
    os.makedirs(os.path.dirname(new_file_path), exist_ok=True)

    yaml = YAML()
    with open(yaml_file, 'r') as file:
        content = yaml.load(file)

    try:
        content['spec']['generators'][0]['merge']['generators'][0]['clusters']['values']['addonChartVersion'] = new_version
        content['spec']['generators'][0]['merge']['generators'][0]['clusters']['values']['addonChartRepository'] = private_ecr_url
    except (KeyError, TypeError):
        print(f"Unable to update values in {yaml_file}")

    with open(new_file_path, 'w') as file:
        file.write('---\n')  # Write the '---' at the start of the file
        yaml.dump(content, file)

    print(f"Copied and updated YAML to: {new_file_path}")
