""" Collection of Zip utility functions """


import os
from zipfile import ZipFile


def zip_folder(folder_path: str, zip_file: ZipFile):
    """
    Create a Zip archive of a folder.
    Note: you'd better use `tarfile` library.
    """
    folder_path = os.path.join(folder_path, "")  # add trailing '/' if missing
    path_length = len(folder_path)
    for root, _dirs, files in os.walk(folder_path):
        folder = root[path_length:]
        for file in files:
            zip_file.write(os.path.join(root, file), os.path.join(folder, file))
