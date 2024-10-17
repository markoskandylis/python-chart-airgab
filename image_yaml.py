import os
from ruamel.yaml import YAML
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_chart_image_values(folder):
    '''
    Get paths of values.yaml or values.yml files in the specified folder.

    :param folder: The root folder to search for values files
    :return: List of paths to values files
    '''
    chart_image_yaml_files = []
    for root, dirs, files in os.walk(folder):
        for file in files:
            if file == 'values.yaml' or file == 'values.yml':
                chart_image_yaml_files.append(os.path.join(root, file))
    logger.info(f"Found {len(chart_image_yaml_files)} values files in {folder}")
    return chart_image_yaml_files

def find_images(content, public_image, private_image, chart_values, parent_keys=[]):
    '''
    Recursively find images in the given content dictionary and create a nested dictionary of key-value pairs.

    :param content: Dictionary representing the YAML content
    :param image: Image name to search for in the content
    :param private_image: Private image URL to replace the public image
    :param chart_values: Dictionary to store key-value pairs
    :param parent_keys: List to track the nested keys
    '''

    public_image_repo = public_image.split(':')[0]
    private_image_repo, private_image_tag = private_image.split(':')

    if isinstance(content, dict):
        for key, value in content.items():
            current_keys = parent_keys + [key]
            if isinstance(value, str) and public_image_repo in value:
                print(f"Creating new values that will replace {value} with {private_image_repo}..")
                d = chart_values
                for k in current_keys[:-2]:
                    d = d.setdefault(k, {})
                d[current_keys[-2]] = {
                    'repository': private_image_repo,
                    'tag': private_image_tag
                }
                logger.info(f"Found {'.'.join(current_keys)}: {value}")
            elif isinstance(value, dict):
                find_images(value, public_image, private_image, chart_values, current_keys)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    find_images(item, public_image, private_image, chart_values, current_keys + [str(index)])
    elif isinstance(content, list):
        for index, item in enumerate(content):
            find_images(item, public_image, private_image, chart_values, parent_keys + [str(index)])
    return chart_values

def extract_chart_values_image(chart_image_yaml_file, public_images, private_images):
    '''
    Extract Docker image information from the values file of a Helm chart.

    :param chart_image_yaml_file: Path to the values.yaml file
    :param public_images: List of public Docker images
    :param private_images: List of private Docker images
    :return: Dictionary containing key-value pairs of found images
    '''
    yaml = YAML()
    with open(chart_image_yaml_file, 'r') as file:
        logger.info(f"Extracting Images from {chart_image_yaml_file}")
        content = yaml.load(file)
        
        # Create a dictionary to store key-value pairs of found images
        chart_values = {}

        print(f"Searching for images: {public_images}")

        try:
            for public_image, private_image in zip(public_images, private_images):
                public_image_name = public_image.split(':')[0].split('/')[-1]
                private_image_name = private_image.split(':')[0].split('/')[-1]
                if public_image_name == private_image_name:
                    chart_values = find_images(content, public_image, private_image, chart_values)
        except Exception as e:
            logger.error(f"Error processing images: {e}")

        print(chart_values)
        return chart_values

def convert_dict_to_yaml(chart_values, output_file):
    '''
    Convert the dictionary of chart values to a YAML file.

    :param chart_values: Dictionary containing key-value pairs of found images
    :param output_file: Path to the output YAML file
    '''
    yaml = YAML()
    
    with open(output_file, 'w') as file:
        yaml.dump(chart_values, file)

    logger.info(f"Updated values saved to {output_file}")