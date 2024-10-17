import argparse
import logging
import os
from yamls import get_yaml_files, extract_values, copy_and_update_yaml
from image_yaml import extract_chart_values_image, convert_dict_to_yaml
from chart import HelmChart

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main(appspec_name, scan_only, push_images, latest=False):
    '''
    Main function to process Helm charts and update them with new versions and image repositories.
    '''
    base_appspec_folder = './application-sets'
    downloaded_chart_folder = './helm-charts'
    new_appspec_folder = './airgaped-application-sets'
    yaml_files = get_yaml_files(base_appspec_folder)

    # Filter the specific appspec file based on the name passed as argument
    yaml_files = [f for f in yaml_files if appspec_name in f]
    print(yaml_files)
    logger.info(f"Found {len(yaml_files)} YAML files in {base_appspec_folder}")
    helm_charts = []
    for yaml_file in yaml_files:
        chart_info = extract_values(yaml_file)
        if chart_info:
            logger.info(chart_info)
            helm_chart = HelmChart(
                addon_chart=chart_info.addon_chart,
                addon_chart_version=chart_info.addon_chart_version,
                addon_chart_repository=chart_info.addon_chart_repository,
                addon_chart_repository_namespace=chart_info.addon_chart_repository_namespace,
                addon_chart_release_name=chart_info.addon_chart_release_name
            )

            try:
                remote_version = helm_chart.get_remote_version(latest)
                if remote_version is None:
                    logger.error(f"Failed to get the version for {helm_chart.addon_chart}")
                    continue
                else:
                    logger.info(f"Using version {remote_version} for {helm_chart.addon_chart}")
            except Exception as e:
                logger.error(f"Failed to get the version for {helm_chart.addon_chart}: {e}")
                continue


            if remote_version:
                try:
                    chart_file = helm_chart.download_chart(downloaded_chart_folder, remote_version)
                    if chart_file:
                        logger.info(f"Chart downloaded to: {chart_file}")
                        helm_chart.get_private_ecr_url()
                        logger.info(f"Private ECR: {helm_chart.private_ecr_url}")
                        helm_chart.get_chart_images(chart_file)
                        logger.info(f"Images extracted from the chart: {helm_chart.public_addon_chart_images}")
                        logger.info(f"Pulling chart Images...")
                        helm_chart.pulling_chart_images()

                        # Scan images before pushing
                        if not helm_chart.scan_images():
                            logger.error("Please Check Vunerabilities.")

                        if push_images or (not scan_only and not push_images):
                            logger.info(f"Pushing Images to ECR...")
                            helm_chart.push_images_to_ecr()
                            logger.info(f"Pushing Chart to ECR...")
                            helm_chart.push_chart_to_ecr(chart_file)

                        if not scan_only:
                            copy_and_update_yaml(yaml_file, new_appspec_folder, base_appspec_folder, new_version=helm_chart.addon_chart_version, private_ecr_url=helm_chart.private_ecr_url)
                            logger.info(f"Updated YAML file copied to: {new_appspec_folder}")
                            values_folder_from_chart_file = f"{os.path.dirname(chart_file)}/{chart_info.addon_chart}/values.yaml"
                            public_images = helm_chart.public_addon_chart_images
                            private_images = helm_chart.private_addon_chart_images
                            chart_values = extract_chart_values_image(values_folder_from_chart_file, public_images, private_images)
                            output_values_folder = f"{os.path.dirname(chart_file)}/values.yaml"
                            convert_dict_to_yaml(chart_values, output_values_folder)
                            helm_charts.append(helm_chart)
                            logger.info(f"Finalised the process\n CHART INFO:\n{helm_chart}\n END!\n")
                    else:
                        logger.error(f"Failed to download chart for {helm_chart.addon_chart}")
                except Exception as e:
                    logger.error(f"Failed to download or push chart: {e}")
            else:
                logger.info(f"No new version available for {helm_chart.addon_chart}")

    for chart in helm_charts:
        logger.info(chart)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process Helm charts and update them with new versions and image repositories.')
    parser.add_argument('--appspec', required=True, help='The name of the appspec to process')
    parser.add_argument('--latest', action='store_true', help='Flag that pulls the latest images ')
    parser.add_argument('--scan-only', action='store_true', help='Flag to only scan images and not push them')
    parser.add_argument('--push-images', action='store_true', help='Flag to push images to ECR')
    args = parser.parse_args()
    main(args.appspec, args.scan_only, args.push_images, args.latest)
