#!/bin/bash

IMAGE_REPO="mginfn"
IMAGE_NAME=interlink-kubernetes-plugin
IMAGE_VERSION=1.0.0
IMAGE_TAG=${IMAGE_REPO}/${IMAGE_NAME}:${IMAGE_VERSION}
IMAGE_TAG_LATEST=${IMAGE_REPO}/${IMAGE_NAME}:latest

CURR_FOLDER=$(pwd)
CTX_FOLDER=src/infr/containers/prod
CTX_APP_FOLDER=${CTX_FOLDER}/app_build

echo Building image ${IMAGE_NAME}:${IMAGE_VERSION}

# Create temp folder to host application build
echo Create application build folder: ${CTX_APP_FOLDER}
mkdir ${CTX_APP_FOLDER}

# Copy application code and data
echo Copy application code to application build folder
cp -r src/app ${CTX_APP_FOLDER}/
cp -r src/infr/charts ${CTX_APP_FOLDER}/infr/
cp src/main.py ${CTX_APP_FOLDER}/
mkdir ${CTX_APP_FOLDER}/private
cp src/private/config.sample.ini ${CTX_APP_FOLDER}/private/

# Export dependencies
poetry export --without-hashes -f requirements.txt -o ${CTX_FOLDER}/requirements.txt

# Build docker image
cd ${CTX_FOLDER}
echo Build command: docker build . -f dockerfile-prod -t ${IMAGE_TAG}
docker build . -f dockerfile-prod -t ${IMAGE_TAG}
echo Build done!

# Clean up
# rm -rf app_build

# Push image
echo Pushing image: ${IMAGE_TAG}
docker push ${IMAGE_TAG}
docker tag ${IMAGE_TAG} ${IMAGE_TAG_LATEST}
docker push ${IMAGE_TAG_LATEST}
echo Tagged latest image: ${IMAGE_TAG_LATEST}

echo Run with: docker run --rm -v ${CURR_FOLDER}/src/private:/interlink-kubernetes-plugin/private -p 30400:4000 ${IMAGE_TAG} uvicorn main:app --host=0.0.0.0 --port=4000 --log-level=debug
echo Done!
