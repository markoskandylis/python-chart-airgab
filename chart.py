import os
import subprocess
import tarfile
import boto3
import logging
from botocore.exceptions import ClientError
from ruamel.yaml import YAML
import json
from pathlib import Path
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HelmChart:
    def __init__(self, addon_chart, addon_chart_version, addon_chart_repository, addon_chart_repository_namespace, addon_chart_release_name, latest=False):
        """
        Initializes the HelmChart with necessary chart details and AWS ECR client.

        Args:
            addon_chart (str): The name of the addon chart.
            addon_chart_version (str): The version of the addon chart.
            addon_chart_repository (str): The repository URL of the addon chart.
            addon_chart_repository_namespace (str): The namespace of the addon chart.
            addon_chart_release_name (str): The release name of the addon chart.
        """
        self.addon_chart = addon_chart
        self.addon_chart_version = addon_chart_version
        self.addon_chart_repository = addon_chart_repository
        self.addon_chart_repository_namespace = addon_chart_repository_namespace
        self.addon_chart_release_name = addon_chart_release_name
        self.public_addon_chart_images = []
        self.private_addon_chart_images = []
        self.failed_pull_addon_chart_images = []
        self.failed_push_addon_chart_images = []
        self.failed_push_addon_chart = None
        self.failed_commands = []
        self.private_ecr_url = None
        self.public_ecr_authenticated = False
        self.private_ecr_authenticated = False
        self.image_vulnerabilities = []

        # Initialize boto3 session and clients once
        self.session = boto3.Session()
        self.region = self.session.region_name
        self.sts_client = self.session.client("sts")
        self.ecr_client = self.session.client("ecr", region_name=self.region)

    def run_command(self, command, error_message):
        """
        Executes a command using subprocess.run and handles errors appropriately.

        Args:
            command (list): The command to run as a list of strings.
            error_message (str): The error message to log in case of failure.

        Returns:
            str: The standard output from the command, or None if the command failed.
        """
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = result.stderr.lower()
            
            # Handle specific known errors
            if "no repo named" in stderr:
                logger.warning("Helm repository 'temp' does not exist. Skipping removal.")
            elif "repository not found" in stderr or "could not resolve host" in stderr:
                logger.warning(f"Remote repository not found or unable to resolve host: {result.stderr}")
                self.failed_commands.append((command, error_message, result.stderr))
            else:
                logger.warning(f"{error_message}: {result.stderr}")
                self.failed_commands.append((command, error_message, result.stderr))
            return None
        return result.stdout
    
    def get_aws_account_id_and_region(self):
        """
        Retrieves AWS account ID and region using STS client.

        Returns:
            tuple: AWS account ID and region.

        Raises:
            Exception: If unable to get caller identity.
        """
        try:
            identity = self.sts_client.get_caller_identity()
            account_id = identity.get("Account")
            return account_id, self.region
        except ClientError as e:
            logger.error(f"Unable to get caller identity: {e}")
            raise Exception(f"Unable to get caller identity: {e}")
        
    def get_private_ecr_url(self):
        """
        Constructs the private ECR URL using AWS account ID and region.
        """
        aws_account_id, region = self.get_aws_account_id_and_region()
        self.private_ecr_url = f"{aws_account_id}.dkr.ecr.{region}.amazonaws.com"

    def authenticate_ecr(self, is_public=False):
        """
        Authenticates Docker to an Amazon ECR registry.

        Args:
            is_public (bool): If True, authenticate to a public ECR. Otherwise, authenticate to a private ECR.

        Raises:
            subprocess.CalledProcessError: If Docker login fails.
        """
        try:
            if is_public:
                if not self.public_ecr_authenticated:
                    self._logout_ecr("public.ecr.aws")
                    self._login_ecr_public()
                    self.public_ecr_authenticated = True
            else:
                if not self.private_ecr_authenticated:
                    self._logout_ecr(self.private_ecr_url)
                    self._login_ecr_private()
                    self.private_ecr_authenticated = True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to authenticate with Amazon ECR: {e}")
            raise e

    def _logout_ecr(self, ecr_url):
        """
        Logs out from a specified ECR registry.

        Args:
            ecr_url (str): The URL of the ECR registry to log out from.
        """
        subprocess.run(["docker", "logout", ecr_url], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _login_ecr_public(self):
        """
        Logs in to the public ECR registry using AWS CLI.
        """
        auth_cmd = ["aws", "ecr-public", "get-login-password", "--region", "us-east-1"]
        auth_output = subprocess.run(auth_cmd, stdout=subprocess.PIPE, check=True)
        auth_password = auth_output.stdout.decode().strip()
        login_cmd = ["docker", "login", "--username", "AWS", "--password-stdin", "public.ecr.aws"]
        subprocess.run(login_cmd, input=auth_password.encode(), check=True)

    def _login_ecr_private(self):
        """
        Logs in to the private ECR registry using AWS CLI.
        """
        auth_cmd = ["aws", "ecr", "get-login-password", "--region", self.region]
        auth_output = subprocess.run(auth_cmd, stdout=subprocess.PIPE, check=True)
        auth_password = auth_output.stdout.decode().strip()
        login_cmd = ["docker", "login", "--username", "AWS", "--password-stdin", self.private_ecr_url]
        subprocess.run(login_cmd, input=auth_password.encode(), check=True)

    def _login_ecr_public_chart(self):
        """
        Logs in to the public ECR registry using Helm CLI.
        """
        auth_cmd = ["aws", "ecr-public", "get-login-password", "--region", "us-east-1"]
        auth_output = subprocess.run(auth_cmd, stdout=subprocess.PIPE, check=True)
        auth_password = auth_output.stdout.decode().strip()
        login_cmd = ["helm", "registry", "login", "--username", "AWS", "--password-stdin", "public.ecr.aws"]
        subprocess.run(login_cmd, input=auth_password.encode(), check=True)

    def _login_ecr_private_chart(self):
        """
        Logs in to the private ECR registry using Helm CLI.
        """
        auth_cmd = ["aws", "ecr", "get-login-password", "--region", self.region]
        auth_output = subprocess.run(auth_cmd, stdout=subprocess.PIPE, check=True)
        auth_password = auth_output.stdout.decode().strip()
        login_cmd = ["helm", "registry", "login", "--username", "AWS", "--password-stdin", self.private_ecr_url]
        subprocess.run(login_cmd, input=auth_password.encode(), check=True)

    def get_remote_version(self, pull_latest=False):
        """
        Compares the desired chart version with the latest available version.
        Returns:
            str: The version that should be used (latest or specified), or None if unavailable.
        """
        if "public.ecr.aws" in self.addon_chart_repository:
            logger.info(f"Fetching version for {self.addon_chart} from OCI registry")
            self._login_ecr_public_chart()
            chart = f"oci://{self.addon_chart_repository}/{self.addon_chart_repository_namespace}/{self.addon_chart}"
            if pull_latest:
                cmd_show_chart = ["helm", "show", "chart", chart]
            else:
                cmd_show_chart = ["helm", "show", "chart", chart, "--version", self.addon_chart_version]
        else:
            logger.info(f"Fetching version for {self.addon_chart} from standard Helm repository")
            if pull_latest:
                cmd_show_chart = ["helm", "show", "chart", self.addon_chart, "--repo", self.addon_chart_repository]
            else:
                cmd_show_chart = ["helm", "show", "chart", self.addon_chart, "--repo", self.addon_chart_repository, "--version", self.addon_chart_version]
        
        try:
            result = self.run_command(cmd_show_chart, "Failed to fetch chart details")
            yaml = YAML()
            chart_info = yaml.load(result)
            version = chart_info.get('version')
            
            if pull_latest:
                logger.info(f"The latest version of {self.addon_chart} is {version}")
                if version != self.addon_chart_version:
                    logger.info(f"New version {version} available for {self.addon_chart}, updating...")
                    self.addon_chart_version = version
                return version
            elif version == self.addon_chart_version:
                logger.info(f"The specified version {self.addon_chart_version} of {self.addon_chart} is available.")
                return version
            else:
                logger.warning(f"The specified version {self.addon_chart_version} of {self.addon_chart} is not available. The latest available version is {version}.")
                return None
        except Exception as e:
            logger.error(f"Failed to fetch chart details: {e}")
            self.failed_commands.append((cmd_show_chart, "Failed to fetch chart details", str(e)))
            return None



    def download_chart(self, destination_folder, version=None):
        """
        Downloads and extracts the Helm chart to the specified destination folder.

        Args:
            destination_folder (str): The folder to download the chart to.
            version (str): The version of the chart to download. Defaults to the chart's version.

        Returns:
            str: The path to the downloaded chart file.

        Raises:
            Exception: If the chart file is not found after download.
        """
        logger.info(f"Downloading and extracting chart {self.addon_chart} version {version if version else self.addon_chart_version}")
        if not version:
            version = self.addon_chart_version
        chart_dir = os.path.join(destination_folder, self.addon_chart)
        os.makedirs(chart_dir, exist_ok=True)

        chart_file = os.path.join(chart_dir, f"{self.addon_chart}-{version}.tgz")
        if os.path.exists(chart_file):
            logger.info(f"Chart file already exists at: {chart_file}")
            with tarfile.open(chart_file, 'r:gz') as tar:
                tar.extractall(path=f"{chart_dir}")
            return chart_file

        if "public.ecr.aws" in self.addon_chart_repository:
            self._login_ecr_public_chart()
            chart = f"oci://{self.addon_chart_repository}/{self.addon_chart_repository_namespace}/{self.addon_chart}"
            cmd_pull_chart = ["helm", "pull", chart, "--version", version, "--destination", chart_dir]
            self.run_command(cmd_pull_chart, "Failed to pull chart from OCI registry")
        else:
            cmd_pull_chart = ["helm", "pull", self.addon_chart, "--repo", self.addon_chart_repository, "--version", version, "--destination", chart_dir]
            self.run_command(cmd_pull_chart, "Failed to pull chart")

        if not os.path.exists(chart_file):
            raise Exception(f"Chart file {chart_file} not found after download")

        with tarfile.open(chart_file, 'r:gz') as tar:
            tar.extractall(path=f"{chart_dir}")

        return chart_file
    
    def get_chart_images(self, chart):
        """
        Extracts images from the Helm chart templates.

        Args:
            chart (str): The path to the chart.

        Raises:
            Exception: If extracting images fails.
        """
        logger.info(f"Getting images for {self.addon_chart}")
        chart_path = Path(chart)
        cmd_get_images = ["helm", "template", str(chart_path), "--set", "clusterName=my-cluster-name"]
        helm_output = self.run_command(cmd_get_images, "Failed to get images")
        cmd_extract_images = ["yq", "..|.image? | select(.)"]
        process = subprocess.Popen(cmd_extract_images, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(input=helm_output)
        unique_images = {image.split('@')[0] if '@' in image else image for image in stdout.splitlines() if image and image != '---'}
        for image in unique_images:
            if "public.ecr.aws" in image:
                logger.info("Authenticating to public ECR")
                self.authenticate_ecr(is_public=True)
            cmd_docker_manifest = ["docker", "manifest", "inspect", image]
            try:
                subprocess.run(cmd_docker_manifest, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.public_addon_chart_images.append(image)
            except subprocess.CalledProcessError:
                logger.warning(f"Skipping image {image} due to failure in manifest inspection")
                self.failed_pull_addon_chart_images.append(image)
        logger.info(f"Extracted images: {self.public_addon_chart_images}")

    def pulling_chart_images(self, retry_count=3, retry_delay=5):
        """
        Pulls Docker images for the chart with retry logic.

        Args:
            retry_count (int): Number of times to retry pulling the images on failure.
            retry_delay (int): Delay between retry attempts in seconds.
        """
        logger.info(f"Pulling images {self.public_addon_chart_images} for chart {self.addon_chart}")
        for image in self.public_addon_chart_images:
            for attempt in range(retry_count):
                try:
                    if "public.ecr.aws" in image:
                        logger.info(f"Pulling public ECR image {image}")
                        self.authenticate_ecr(is_public=True)
                        cmd_pull_image = ["docker", "pull", image]
                        self.run_command(cmd_pull_image, f"Failed to pull image {image}")
                    else:
                        logger.info(f"Pulling image {image}")
                        self.authenticate_ecr(is_public=False)
                        cmd_pull_image = ["docker", "pull", image]
                        self.run_command(cmd_pull_image, f"Failed to pull image {image}")
                    break
                except Exception as e:
                    logger.error(f"Attempt {attempt + 1} failed to pull image {image}: {e}")
                    if attempt + 1 < retry_count:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                    else:
                        logger.error(f"Maximum attempts reached for pulling image {image}.")
                        self.failed_pull_addon_chart_images.append(image)
    def scan_image(self, image):
        """
        Scans an image for vulnerabilities using Trivy and updates the vulnerabilities list.

        Args:
            image (str): The Docker image to scan.
        
        Returns:
            bool: True if no critical vulnerabilities found, False otherwise.
        """
        logger.info(f"Scanning image: {image}")
        try:
            result = subprocess.run(['trivy', 'image', '--exit-code', '1', '--severity', 'CRITICAL', image], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logger.info(f"Scan result for {image}: {result.stdout.decode('utf-8')}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Image scanning failed for {image}. Error: {e.stderr.decode('utf-8')}\nOutput: {e.stdout.decode('utf-8')}")
            self.image_vulnerabilities.append({
                'image': image,
                'error': e.stderr.decode('utf-8'),
                'output': e.stdout.decode('utf-8')
            })
            return False

    def scan_images(self):
        """
        Scans all images in the public_addon_chart_images list and updates their status.
        """
        logger.info("Scanning images for vulnerabilities.")
        all_images_passed = True
        for image in self.public_addon_chart_images:
            if not self.scan_image(image):
                all_images_passed = False
        return all_images_passed

    def push_images_to_ecr(self, retry_count=3, retry_delay=5):
        """
        Pushes Docker images to the private ECR repository with retry logic.

        Args:
            retry_count (int): Number of times to retry pushing the images on failure.
            retry_delay (int): Delay between retry attempts in seconds.
        """
        for public_repo in self.public_addon_chart_images:
            image_name = public_repo.rsplit('/', 1)[-1]
            image_with_chart_prefix = f"{self.addon_chart}/{image_name}"
            private_image = f"{self.private_ecr_url}/{image_with_chart_prefix}"
            self.private_addon_chart_images.append(private_image)
            try:
                logger.info(f"Tagging Image for Private ECR")
                docker_tag = ["docker", "tag", public_repo, private_image]
                self.run_command(docker_tag, f"Failed to tag image {public_repo} to {private_image}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to tag image {public_repo} to {private_image}: {e}")
                raise e

            try:
                ecr_repo = image_with_chart_prefix.split(':')[0]
                self.ecr_client.describe_repositories(repositoryNames=[ecr_repo])
                logger.info(f"ECR repository {ecr_repo} exists.")
            except ClientError as e:
                if e.response['Error']['Code'] == 'RepositoryNotFoundException':
                    logger.info(f"Repository {ecr_repo} not found, creating new repository...")
                    try:
                        self.ecr_client.create_repository(repositoryName=ecr_repo)
                    except ClientError as create_err:
                        logger.error(f"Unable to create ECR repository: {create_err}")
                else:
                    logger.error(f"Error describing ECR repositories: {e}")

            self.authenticate_ecr(is_public=False)
            logger.info(f"Pushing image to private ECR: {private_image}")
            for attempt in range(retry_count):
                try:
                    push_command = ["docker", "push", private_image]
                    result = self.run_command(push_command, f"Failed to push image {public_repo} to {private_image}")
                    if result is not None:
                        logger.info(f"Successfully pushed {public_repo} to {private_image}.")
                        break
                    else:
                        logger.warning(f"Attempt {attempt + 1} failed to push image {public_repo} to {private_image}")
                        if attempt + 1 < retry_count:
                            logger.info(f"Retrying in {retry_delay} seconds...")
                            time.sleep(retry_delay)
                        else:
                            logger.error(f"Maximum attempts reached for pushing image {public_repo} to {private_image}.")
                            self.failed_push_addon_chart_images.append(private_image)
                except Exception as e:
                    logger.error(f"Unexpected error occurred while pushing image {public_repo} to {private_image}: {e}")
                    self.failed_push_addon_chart_images.append(private_image)

    def push_chart_to_ecr(self, chart_file, retry_count=5, retry_delay=10):
        """
        Pushes the Helm chart to the private ECR repository with retry logic.

        Args:
            chart_file (str): The path to the chart file.
            retry_count (int): Number of times to retry pushing the chart on failure.
            retry_delay (int): Delay between retry attempts in seconds.

        Raises:
            Exception: If creating or describing the ECR repository fails, or if pushing the chart fails.
        """
        try:
            self.ecr_client.describe_repositories(repositoryNames=[self.addon_chart])
            logger.info(f"ECR repository {self.private_ecr_url}/{self.addon_chart} exists.")
        except ClientError as e:
            if e.response["Error"]["Code"] == "RepositoryNotFoundException":
                logger.info(f"Repository {self.private_ecr_url}/{self.addon_chart} not found, creating new repository...")
                try:
                    self.ecr_client.create_repository(repositoryName=self.addon_chart)
                except ClientError as create_err:
                    logger.error(f"Unable to create ECR repository: {create_err}")
                    raise Exception(f"Unable to create ECR repository: {create_err}")
            else:
                logger.error(f"Error describing ECR repositories: {e}")
                raise Exception(f"Error describing ECR repositories: {e}")

        try:
            self.ecr_client.describe_images(repositoryName=self.addon_chart, imageIds=[{"imageTag": self.addon_chart_version}])
            logger.info(f"Chart {self.addon_chart} version {self.addon_chart_version} already exists in ECR, skipping push")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ImageNotFoundException":
                logger.error(f"Error checking for image existence: {e}")
                raise Exception(f"Error checking for image existence: {e}")

        self.authenticate_ecr(is_public=False)
        for attempt in range(retry_count):
            try:
                cmd_push_chart = ["helm", "push", chart_file, f"oci://{self.private_ecr_url}"]
                result = self.run_command(cmd_push_chart, "Failed to push chart to ECR")
                if result is not None:
                    logger.info(f"Successfully pushed {self.addon_chart} to ECR.")
                    break
                else:
                    logger.warning(f"Attempt {attempt + 1} failed to push chart {chart_file} to {self.private_ecr_url}")
                    if attempt + 1 < retry_count:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                    else:
                        logger.error(f"Maximum attempts reached for pushing chart {chart_file} to {self.private_ecr_url}.")
                        self.failed_push_addon_chart_images.append(chart_file)
            except Exception as e:
                logger.error(f"Unexpected error occurred while pushing chart {chart_file} to {self.private_ecr_url}: {e}")
                self.failed_push_addon_chart_images.append(chart_file)

    def __str__(self):
        """
        Returns a string representation of the HelmChart instance.
        """
        return (f"addon_chart='{self.addon_chart}'\n"
                f"addon_chart_version='{self.addon_chart_version}'\n"
                f"addon_chart_repository='{self.addon_chart_repository}'\n"
                f"addon_chart_repository_namespace='{self.addon_chart_repository_namespace}'\n"
                f"addon_chart_release_name='{self.addon_chart_release_name}'\n"
                f"private_ecr_url='{self.private_ecr_url}'\n"
                f"public_addon_chart_images='{self.public_addon_chart_images}'\n"
                f"private_addon_chart_images='{self.private_addon_chart_images}'\n"
                f"image_vulnerabilities='{self.image_vulnerabilities}'\n"
                f"failed_pull_addon_chart_images='{self.failed_pull_addon_chart_images}'\n"
                f"failed_push_addon_chart_images='{self.failed_push_addon_chart_images}'\n"
                f"failed_commands='{self.failed_commands}'\n")
