import json
import os
import tarfile
from os.path import join as path_join
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional

import backoff
import boto3
import botocore.exceptions as boto_exceptions
import pydash as _
from botocore.client import Config as ClientConfig
from botocore.exceptions import ClientError

from app.common.config import Config, Option
from sdk.common.logger import logger
from sdk.utilities import file_utilities

BOTOCORE_EXCEPTIONS_TO_RETRY = (
    boto_exceptions.EndpointConnectionError,
    boto_exceptions.ReadTimeoutError,
    boto_exceptions.ConnectTimeoutError,
    # boto_exceptions.IncompleteSignatureError,
    # boto_exceptions.ServiceUnavailableError,
    # Note: throttling and request limit errors are typically encapsulated within botocore.exceptions.ClientError
    # and you need to inspect the error code within the ClientError to determine if it is a throttling issue.
    # boto_exceptions.ThrottlingError,
    # boto_exceptions.RequestLimitExceeded,
)
"""
botocore.exceptions.EndpointConnectionError:
    Indicates that the connection attempt timed out. Retrying can be effective if the network congestion clears up.
botocore.exceptions.ReadTimeoutError:
    Indicates that the read operation timed out. This can happen in case of slow network conditions.
botocore.exceptions.IncompleteSignatureError:
    Indicates that the request signature does not match, which can be due to temporary issues with the request
    construction or network problems.
botocore.exceptions.ServiceUnavailableError:
    Indicates that the service is temporarily unavailable. Retrying can be effective once the service recovers.
botocore.exceptions.ThrottlingError:
    Indicates that the request rate is too high and the client is being throttled. AWS suggests using exponential
    backoff and retrying.
botocore.exceptions.RequestLimitExceeded:
    Indicates that the request limit has been exceeded. Similar to throttling, using exponential backoff and retrying
     can help.
"""


class S3Client:

    # _instance: ClassVar["S3Client"]
    # def __new__(cls, *args, **kwargs):
    #     if cls._instance is None:
    #         cls._instance = super(S3Client, cls).__new__(cls, *args, **kwargs)
    #     return cls._instance

    bucket_name: str
    endpoint_url: str

    def __init__(self, bucket: Optional[str] = None, endpoint_url: Optional[str] = None):
        self.bucket_name = bucket if bucket is not None else Config.get(Option.S3_BUCKET)
        self.endpoint_url = endpoint_url if endpoint_url is not None else Config.get(Option.S3_ENDPOINT_URL)

        client_config = ClientConfig(
            # retries = {
            #     'max_attempts': 5,
            #     'mode': 'standard'
            # }
        )

        self.s3_client = boto3.client("s3", config=client_config, endpoint_url=self.endpoint_url)

    @backoff.on_exception(backoff.expo, BOTOCORE_EXCEPTIONS_TO_RETRY, max_tries=3)
    def put_object(self, file: bytes, object_key: str) -> bool:
        try:
            logger.info("Put object '%s' to S3 Bucket '%s'", object_key, self.bucket_name)
            self.s3_client.put_object(Bucket=self.bucket_name, Key=object_key, Body=file)  # type: ignore
            logger.info("Put of object '%s' SUCCEEDED", object_key)
        except ClientError as err:
            logger.error(err)
            raise err
        return True

    @backoff.on_exception(backoff.expo, BOTOCORE_EXCEPTIONS_TO_RETRY, max_tries=3)
    def delete_objects(self, object_keys: List[str]) -> bool:
        list_of_keys = _.map_(object_keys, lambda key: {"Key": key})
        try:
            logger.info("Delete objects '%s' from S3 Bucket '%s'", json.dumps(list_of_keys), self.bucket_name)
            self.s3_client.delete_objects(Bucket=self.bucket_name, Delete={"Objects": list_of_keys})  # type: ignore
            logger.info("Delete of objects SUCCEEDED")
        except ClientError as err:
            logger.error(err)
            raise err
        return True

    @backoff.on_exception(backoff.expo, BOTOCORE_EXCEPTIONS_TO_RETRY, max_tries=3)
    def upload_file(self, file_path: str, object_key: Optional[str] = None) -> bool:
        """Upload a local file to the S3 bucket.

        :param file_path: Path to the file to upload
        :param object_key: S3 object key (if None, the final component of file_path)
        :return: True if uploaded succeeded
        :raise: Exception if upload failed

        See https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3-uploading-files.html
        TODO Callback
        """

        if object_key is None:
            object_key = os.path.basename(file_path)

        try:
            logger.info("Upload file '%s' to S3 Bucket '%s' with key '%s'", file_path, self.bucket_name, object_key)
            self.s3_client.upload_file(Filename=file_path, Bucket=self.bucket_name, Key=object_key)  # type: ignore
            logger.info("Upload of file '%s' SUCCEEDED", file_path)
        except ClientError as err:
            logger.error(err)
            raise err
        return True

    def upload_folder(
        self, folder_path: str, object_prefix_or_key: Optional[str] = None, do_compress: bool = False
    ) -> bool:
        """Upload a local folder to the S3 bucket.

        If not do_compress, upload all files at the given `folder_path` to S3;
        else, compress the folder (keep `folder_path`'s base name as root folder in the tarball)
        and upload a single file to S3.

        :param folder_path: Path to the folder to upload
        :param object_prefix_or_key:
            - if not `do_compress`, S3 object prefix for all files ('' if None);
            - else, S3 object key of the compressed archive (if None, the final component of folder_path)
        :param do_compress: if True, compress and then upload
        :return: True if uploaded succeeded
        :raise: Exception if upload failed
        """
        if do_compress:
            if not object_prefix_or_key:
                object_prefix_or_key = os.path.basename(folder_path)
            with TemporaryDirectory() as temp_dir:
                temp_tar_file = f"{temp_dir}/temp.tar.gz"
                with tarfile.open(temp_tar_file, "w:gz") as tar_file:
                    tar_file.add(folder_path, arcname=os.path.basename(folder_path))
                return self.upload_file(temp_tar_file, object_prefix_or_key)
        else:
            raise NotImplementedError()

    @backoff.on_exception(backoff.expo, BOTOCORE_EXCEPTIONS_TO_RETRY, max_tries=3)
    def download_file(
        self, object_key: str, folder_path_to_save: str, try_extract: bool = True, create_folder: bool = True
    ) -> bool:
        """Download a file from the S3 bucket and save to the provided folder.

        If `try_extract`, download the S3 object and if it's a supported archive format, extract it to
        `folder_path_to_save`;
        else, save the downloaded S3 object to `folder_path_to_save/basename(object_key)`;

        :param object_key: S3 object key
        :param folder_path_to_save: Path to the folder to save
        :param try_extract: if True, after downloading check file's format and eventually extract
        :param create_folder: if True and `folder_path_to_save` does not exist, create it recursively
        :return: True if success
        :raise: Exception if failure
        """
        if not os.path.isdir(folder_path_to_save):
            if not create_folder:
                raise RuntimeError(f"Destination folder does not exist: '{folder_path_to_save}'")
            else:
                os.makedirs(folder_path_to_save)

        file_name = os.path.basename(object_key)
        file_extension = file_utilities.get_file_extension(file_name)
        dest_file_path = path_join(folder_path_to_save, file_name)
        logger.info(
            "Download file '%s' from S3 Bucket '%s' to local folder '%s'",
            object_key,
            self.bucket_name,
            folder_path_to_save,
        )
        self.s3_client.download_file(Bucket=self.bucket_name, Key=object_key, Filename=dest_file_path)
        logger.info("Download of file '%s' SUCCEEDED", object_key)

        if try_extract and file_extension in ("tar.gz",):
            with tarfile.open(dest_file_path, "r") as tar_file:
                tar_file.extractall(folder_path_to_save)
            os.remove(dest_file_path)
        return True

    def download_folder(self, object_prefix: str, folder_path_to_save: str, create_folder: bool = True) -> bool:
        """Download all objects with the given `object_prefix` and save to the provided folder.

        :param object_prefix: S3 objects prefix
        :param folder_path_to_save: Path to the folder to save
        :param create_folder: if True and `folder_path_to_save` does not exist, create it recursively
        :return: True if success
        :raise: Exception if failure
        """
        paginator = self.s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self.bucket_name, Prefix=object_prefix)

        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    object_key: str = obj["Key"]  # type: ignore
                    object_child_prefix = object_key[len(object_prefix) + 1 :]  # noqa: E203
                    self.download_file(
                        object_key, path_join(folder_path_to_save, object_child_prefix), False, create_folder
                    )
        return True

    @backoff.on_exception(backoff.expo, BOTOCORE_EXCEPTIONS_TO_RETRY, max_tries=3)
    def list_objects(
        self, object_prefix: Optional[str] = None, max_keys: int = 1000, continuation_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Returns some or all (up to 1,000) of the objects in the bucket with the given prefix"""
        kwargs = {"Bucket": self.bucket_name, "MaxKeys": max_keys}
        if object_prefix:
            kwargs.update({"Prefix": object_prefix})
        if continuation_token:
            kwargs.update({"ContinuationToken": continuation_token})
        return self.s3_client.list_objects_v2(**kwargs)  # type: ignore # ListObjectsV2OutputTypeDef
