import json
import logging
import re
import getpass
import os
import requests
from pathlib import Path
import threading
import uuid
import zipfile


import filetype
from socketIO_client import SocketIO, BaseNamespace
import yaml


logger = logging.getLogger(__name__)
BASE_URL = "https://sharelatex.irisa.fr"


def browse_project(client, login_data, project_id, path="."):
    """NOTE(msimonin): je me rappelle pas ce que c'est censé faire."""
    r = client.post(LOGIN_URL, data=login_data, verify=True)
    project_url = "{base}/project/{pid}".format(base=BASE_URL, pid=project_id)
    r = client.get(project_url)


_api_lock = threading.Lock()
# Keep track of the api client (singleton)
_api_client = None


def get_client():
    """Gets the reference to the API cient (singleton)."""
    with _api_lock:
        global _api_client
        if not _api_client:
            conf_file = os.path.join(os.environ.get("HOME"), ".sharelatex.yaml")
            _api_client = SyncClient.from_yaml(filepath=conf_file)

        return _api_client


def walk_project_data(project_data, predicate=lambda x: True):
    """Iterate on the project entities (folders, files).

    Args:
        project_data (dict): the project data as retrieved by
            :py:meth:`sharelatex.SyncClient.get_project_data`
        predicate: lambda to filter the entry
            an entry is a dictionnary as in
            {"folder_id": <id of the current folder>,
             "folder_path": <complete path of the folder /a/folder/>,
             "name": <name of the entity>,
             "type": <type of the entity directory or file>,
             "_id" : <id of the entity>

    Returns:
        A generator for the matching entities
    """

    def _walk_project_data(current, parent):
        """Iterate on the project structure

        Args:
            current (dict): current folder representation
            parent (str): path of the parent folder
        """
        for c in current:
            if c["name"] == "rootFolder":
                folder_name = ""
            else:
                folder_name = c["name"]
            folder_path = os.path.join(parent, folder_name)
            fd = {
                "folder_id": c["_id"],
                "folder_path": folder_path,
                "name": folder_name,
            }
            fd.update(type="folder")
            if predicate(fd):
                yield fd
            for f in c["fileRefs"]:
                fd.update(f)
                fd.update(type="file")
                if predicate(fd):
                    yield fd
            for d in c["docs"]:
                fd.update(d)
                fd.update(type="file")
                if predicate(fd):
                    yield fd
            if len(c["folders"]) > 0:
                yield from _walk_project_data(c["folders"], folder_path)

    return _walk_project_data(project_data["rootFolder"], "/")


def lookup_folder(project_data, folder_path):
    """Lookup a folder by its path

    Args:
        project_data (dict): the project data as retrieved by
            :py:meth:`sharelatex.SyncClient.get_project_data`
        folder_path (str): the path of the folder. Must start with ``/``.

    Returns:
        The folder id (str)

    Raises:
         StopIteration if the folder isn't found
    """
    folders = walk_project_data(
        project_data, predicate=lambda x: x["folder_path"] == folder_path
    )
    return next(folders)


def walk_files(project_data):
    """Iterates on the file only of a project.

    Args:
        project_data (dict): the project data as retrieved by
            :py:meth:`sharelatex.SyncClient.get_project_data`
    """
    return walk_project_data(project_data, lambda x: x["type"] == "file")


class SyncClient:
    def __init__(self, *, base_url=BASE_URL, username=None, password=None, verify=True):
        """Creates the client.

        This mimics the browser behaviour when logging in.


        Args:
            base_url (str): base url of the sharelatex server
            username (str): username of the user (the email)
            password (str): password of the user
            verify (bool): True iff SSL certificates must be verified
        """

        self.base_url = base_url
        self.verify = verify

        # build the client and login
        self.client = requests.session()
        login_url = "{}/login".format(self.base_url)

        # Retrieve the CSRF token first
        r = self.client.get(login_url, verify=True)
        self.csrf = re.search('(?<=csrfToken = ").{36}', r.text).group(0)

        # login
        self.login_data = {"email": username, "password": password, "_csrf": self.csrf}

        _r = self.client.post(login_url, data=self.login_data, verify=self.verify)
        _r.raise_for_status()
        self.login_data.pop("password")
        self.sharelatex_sid = _r.cookies["sharelatex.sid"]

    @classmethod
    def from_yaml(cls, *, filepath=None):
        if not filepath:
            filepath = Path(os.environ.get("HOME"), ".sync_sharelatex.yaml")
        with open(filepath, "r") as f:
            conf = yaml.load(f, Loader=yaml.BaseLoader)
            return cls(**conf)

    def get_project_data(self, project_id):
        """Get the project hierarchy and some metadata.

        This mimics the browser behaviour when opening the project editor. This
        will open a websocket connection to the server to get the informations.

        Args:
            project_id (str): the id of the project
        """

        url = f"{self.base_url}/project/{project_id}"

        # use thread local storage to pass the project data
        storage = threading.local()

        class Namespace(BaseNamespace):
            def on_connect(self):
                logger.debug("[Connected] Yeah !!")

            def on_reconnect(self):
                logger.debug("[Reconnected] re-Yeah !!")

            def on_disconnect(self):
                logger.debug("[Disconnected]  snif!  ")

        def on_joint_project(*args):
            storage.project_data = args[1]

        def on_connection_rejected(*args):
            logger.debug("[connectionRejected]  oh !!!")

        with SocketIO(
            self.base_url,
            verify=self.verify,
            Namespace=Namespace,
            cookies={"sharelatex.sid": self.sharelatex_sid},
            headers={"Referer": url},
        ) as socketIO:

            def on_connection_accepted(*args):
                logger.debug("[connectionAccepted]  Waoh !!!")
                socketIO.emit(
                    "joinProject", {"project_id": project_id}, on_joint_project
                )

            socketIO.on("connectionAccepted", on_connection_accepted)
            socketIO.on("connectionRejected", on_connection_rejected)
            socketIO.wait(seconds=3)
        # NOTE(msimonin): Check return type
        # thuis must be a valid dict (eg not None)
        return storage.project_data

    def get_project_iter(self, project_id):
        """Returns a iterator on the files of a project."""

        project_data = self.get_project_data(project_id)
        return walk_project_data(current, lambda x: x["type"] == "file")

    def download_project(self, project_id, *, path=".", keep_zip=False):
        """Download and unzip the project.

        Beware that this will overwrite any existing project file under path.

        Args:
            project_id (str): the id of the project to download
            path (str): a valid path where the files will be saved.
        """
        url = f"{self.base_url}/project/{project_id}/download/zip"
        r = self.client.get(url, stream=True)

        logger.info(f"Downloading {project_id} in {path}")
        target_dir = Path(path)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = Path(target_dir, f"{project_id}.zip")
        with open(str(target_path), "wb") as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)

        logger.info(f"Unzipping {project_id} in {path}")
        with zipfile.ZipFile(target_path) as zip_file:
            zip_file.extractall(path=path)

        if not keep_zip:
            target_path.unlink()

    def get_doc(self, project_id, doc_id):
        """TODO(msimonin): the route is currently private on the server side

        see https://gitlab.inria.fr/sed-rennes/sharelatex/web-sharelatex/blob/inria-1.2.1/app/coffee/router.coffee#L253
        """
        url = f"{self.base_url}/project/{project_id}/doc/{doc_id}"
        r = self.client.get(url, data=self.login_data, verify=self.verify)

        # TODO(msimonin): return type
        return r

    def get_file(self, project_id, file_id):
        url = f"{self.base_url}/project/{project_id}/file/{file_id}"
        r = self.client.get(url, data=self.login_data, verify=self.verify)

        # TODO(msimonin): return type
        return r

    def get_document(self, project_id, doc_id):
        url = f"{self.base_url}/project/{project_id}/document/{doc_id}"
        r = self.client.get(url, data=self.login_data, verify=self.verify)

        # TODO(msimonin): return type
        return r

    def upload_file(self, project_id, folder_id, path):
        """Upload a file to sharelatex.

        Args:
            project_id (str): the project id
            folder_id (str): the parent folder
            path (str): local path to the file
        """
        url = f"{self.base_url}/project/{project_id}/upload"
        filename = os.path.basename(path)
        # TODO(msimonin): handle correctly the content-type
        mime = filetype.guess(path)
        if not mime:
            mime = "text/plain"
        files = {"qqfile": (filename, open(path, "rb"), mime)}
        params = {
            "folder_id": folder_id,
            "_csrf": self.csrf,
            "qquid": str(uuid.uuid4()),
            "qqfilename": filename,
            "qqtotalfilesize": os.path.getsize(path),
        }
        r = self.client.post(url, params=params, files=files, verify=self.verify)
        r.raise_for_status()
        response = r.json()
        if not response["success"]:
            raise Exception(f"Uploading {path} fails")
        return response

    def create_folder(self, project_id, parent_folder, name):
        """Create a folder on sharelatex.

        Args:
            project_id (str): The project id of the project to create the folder in
            parent_folder (str): The id of the folder to create the folder in
            name (str): Name of the folder

        Returns:
            response (dict) status of the request as returned by sharelatex

        Raises:
            Something wrong with sharelatex
            - 500 server error
            - 400 the folder already exists
        """
        url = f"{self.base_url}/project/{project_id}/folder"
        data = {"parent_folder_id": parent_folder, "_csrf": self.csrf, "name": name}
        logger.debug(data)
        r = self.client.post(url, data=data, verify=self.verify)
        r.raise_for_status()
        response = r.json()
        return response

    def check_or_create_folder(self, metadata, folder_path):
        """Check if a given folder exists on sharelatex side.

        Create it recursively if needed and return its id.
        It looks in the metadata and create the missing directories.
        Make sure the metadata are up-to-date when calling this.

        Args:
            metadata (dict): the sharelatex metadata as a structure basis
            folder_path (str): the folder path

        Returns:
            The folder id
        """
        try:
            folder = lookup_folder(metadata, folder_path)
            return folder["folder_id"]
        except:
            logger.debug(f"{folder_path} not found, creation planed")

        parent_folder = os.path.dirname(folder_path)
        parent_id = self.check_or_create_folder(metadata, os.path.dirname(folder_path))
        new_folder = self.create_folder(
            metadata["_id"], parent_id, os.path.basename(folder_path)
        )
        return new_folder["_id"]

    def upload(self, path):
        """Upload a project (zip) to sharelatex.

        Args:
            path (str): path to the zip file of a project.
        """
        url = f"{self.base_url}/project/new/upload"
        filename = os.path.basename(path)
        mime = "application/zip"
        files = {"qqfile": (filename, open(path, "rb"), mime)}
        params = {
            "_csrf": self.csrf,
            "qquid": str(uuid.uuid4()),
            "qqfilename": filename,
            "qqtotalfilesize": os.path.getsize(path),
        }
        r = self.client.post(url, params=params, files=files, verify=self.verify)
        r.raise_for_status()
        response = r.json()
        if not response["success"]:
            raise Exception(f"Uploading {path} fails")
        return response

    def compile(self, project_id):
        """Trigger a remote compilation.

        Note that this is run against the remote version not the local one.

        Args:
            project_id (str): the project id of the project to compile
        """

        url = f"{self.base_url}/project/{project_id}/compile"

        data = {
            "_csrf": self.csrf,
        }
        r = self.client.post(url, data=data, verify=self.verify)
        r.raise_for_status()
        response = r.json()
        return response
