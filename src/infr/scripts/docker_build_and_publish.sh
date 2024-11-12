#!/bin/bash

IMAGE_NAME=interlink-kubernetes-plugin
IMAGE_VERSION=0.0.1
DOCKER_REPO="mginfn"

CTX_FOLDER=infr/containers/prod
CTX_APP_FOLDER=${CTX_FOLDER}/app_build

echo Building image ${IMAGE_NAME}:${IMAGE_VERSION}

# Create temp folder to host application build
echo Create application build folder: ${CTX_APP_FOLDER}
mkdir ${CTX_APP_FOLDER}

# Copy application code and scripts
echo Copy application code to application build folder
cp -r src/* ${CTX_APP_FOLDER}/
# cp -r libs ${CTX_APP_FOLDER}/
cp -r infr/scripts ${CTX_APP_FOLDER}/

# Export dependencies
poetry export --without dev --without-hashes -f requirements.txt -o ${CTX_FOLDER}/requirements.txt

# Build docker image
cd ${CTX_FOLDER}
echo Build command: docker build . -f dockerfile-prod -t ${IMAGE_NAME}:${IMAGE_VERSION}
docker build . -f dockerfile-prod -t ${IMAGE_NAME}:${IMAGE_VERSION}

# Clean up
rm -rf app_build

# Push image
echo Pushing image ${IMAGE_NAME}:${IMAGE_VERSION}
docker push ${DOCKER_REPO}/${IMAGE_NAME}:${IMAGE_VERSION}

echo Done
