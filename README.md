# Chart and YAML Processing Tools

This repository contains a set of tools for handling charts and processing YAML files, particularly for operations related to container images and Elastic Container Registry (ECR).

## Files Overview

### `chart.py`
This file contains functions for managing charts, including:
- Pulling Helm Charts
- Checking Required Docker Images
- Pulling Docker Images
- Tagging Docker images
- Pushing Docker images to private ECR repositories
- Handling repository creation if it does not exist

### `image_yaml.py`
This file includes functionalities for processing YAML files, such as:
- Loading and extracting values from YAML files
- Copying and updating YAML files with new versions and repository URLs

### `main.py`
The main entry point for the application, coordinating the execution of functionalities provided in the other files.

### `yamls.py`
Utilities for handling YAML files, including:
- Loading YAML content
- Copying YAML files to new destinations
- Updating specific values within YAML files

## Installation

To install the required dependencies, run the following command:

```bash
pip install -r requirements.txt
