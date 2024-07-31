#!/bin/bash

IMAGE_NAME=interlink-kubernetes-plugin
IMAGE_VERSION=0.0.1

BUILD_CTX_FOLDER=infr/containers/prod
BUILD_APP_FOLDER=${BUILD_CTX_FOLDER}/app_build

echo Building image ${IMAGE_NAME}:${IMAGE_VERSION}

# Create temp folder to host application build
echo Create application build folder: ${BUILD_APP_FOLDER}
mkdir ${BUILD_APP_FOLDER}

# Copy application code and scripts
echo Copy application code to application build folder
cp -r src/* ${BUILD_APP_FOLDER}/
cp -r libs ${BUILD_APP_FOLDER}/
cp -r infr/scripts ${BUILD_APP_FOLDER}/

# Export dependencies
poetry export --without-hashes --with kubeflow -f requirements.txt -o ${BUILD_CTX_FOLDER}/requirements.txt

# Build docker image
cd ${BUILD_CTX_FOLDER}
echo Build command: docker build . -f dockerfile-prod -t ${IMAGE_NAME}:${IMAGE_VERSION}
docker build . -f dockerfile-prod -t ${IMAGE_NAME}:${IMAGE_VERSION}

# Clean up
rm -rf app_build

# Push image
echo Pushing image ${IMAGE_NAME}:${IMAGE_VERSION}
docker push mginfn/${IMAGE_NAME}:${IMAGE_VERSION}

echo Done
