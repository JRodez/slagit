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


from .__version__ import __version__


logger = logging.getLogger(__name__)
BASE_URL = "https://sharelatex.irisa.fr"
USER_AGENT = f"python-sharelatex {__version__}"


class SharelatexError(Exception):
    """Base class for the errors here."""

    pass


class CompilationError(SharelatexError):
    def __init__(self, json_status):
        super().__init__("Compilation failed", json_status)


def walk_project_data(project_data, predicate=lambda x: True):
    """Iterate on the project entities (folders, files).

    Args:
        project_data (dict): The project data as retrieved by
            :py:meth:`sharelatex.SyncClient.get_project_data`
        predicate (lambda): Lambda to filter the entry
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
            current (dict): Current folder representation
            parent (str): Path of the parent folder
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
                fd.update(type="doc")
                if predicate(fd):
                    yield fd
            if len(c["folders"]) > 0:
                yield from _walk_project_data(c["folders"], folder_path)

    return _walk_project_data(project_data["rootFolder"], "/")


def lookup_folder(project_data, folder_path):
    """Lookup a folder by its path

    Args:
        project_data (dict): The project data as retrieved by
            :py:meth:`sharelatex.SyncClient.get_project_data`
        folder_path (str): The path of the folder. Must start with ``/``

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
        project_data (dict): The project data as retrieved by
            :py:meth:`sharelatex.SyncClient.get_project_data`

    Raises:
        StopIteration if the file isn't found
    """
    return walk_project_data(project_data, lambda x: x["type"] == "file")


def check_error(json):
    """Check if there's an error in the returned json from sharelatex.

    This assumes json to be a dict like the following
    {
        "message":
         {
              "text": "Your email or password is incorrect. Please try again",
              "type": "error"
         }
    }

    Args:
        json (dict): message returned by the sharelatex server

    Raise:
        Exception with the corresponding text in the message
    """
    message = json.get("message")
    if message is None:
        return
    t = message.get("type")
    if t is not None and t == "error":
        raise Exception(message.get("text", "Unknown error"))


def get_csrf_Token(html_text):
    """Retrieve csrf token from a html text page from sharelatex server.

    Args:
        html_text (str): The text from a html page of sharelatex server
    Returns:
        the csrf token (str) if found in html_text or None if not
    """
    if "csrfToken" in html_text:
        return re.search('(?<=csrfToken = ").{36}', html_text).group(0)
    else:
        return None


class SyncClient:
    def __init__(self, *, base_url=BASE_URL, username=None, password=None, verify=True):
        """Creates the client.

        This mimics the browser behaviour when logging in.


        Args:
            base_url (str): Base url of the sharelatex server
            username (str): Username of the user (the email)
            password (str): Password of the user
            verify (bool): True iff SSL certificates must be verified
        """
        if base_url == "":
            raise Exception("projet_url is not well formed or missing")
        self.base_url = base_url
        self.verify = verify

        # Used in _get, _post... to add common headers
        self.headers = {"user-agent": USER_AGENT}

        # build the client and login
        self.client = requests.session()
        login_url = "{}/login".format(self.base_url)

        # Retrieve the CSRF token first
        r = self._get(login_url, verify=self.verify)
        self.csrf = get_csrf_Token(r.text)
        if self.csrf:
            self.login_data = {
                "email": username,
                "password": password,
                "_csrf": self.csrf,
            }
            # login
            _r = self._post(login_url, data=self.login_data, verify=self.verify)
            _r.raise_for_status()
            check_error(_r.json())
        else:
            # try to find CAS form
            from lxml import html

            a = html.fromstring(r.text)
            if len(a.forms) == 1:
                fo = a.forms[0]
                if "execution" in fo.fields.keys():  # seems to be CAS !
                    self.login_data = {name: value for name, value in fo.form_values()}
                    self.login_data["password"] = password
                    self.login_data["username"] = username
                    login_url = r.url
                    _r = self._post(login_url, data=self.login_data, verify=self.verify)
                    _r.raise_for_status()
                    self.csrf = get_csrf_Token(_r.text)
                    if self.csrf == None:
                        raise Exception("csrf token error")
                else:
                    raise Exception(
                        "authentication page not found or not yet supported"
                    )
            else:
                raise Exception("authentication page not found")

        self.login_data.pop("password")
        self.sharelatex_sid = _r.cookies["sharelatex.sid"]

    def get_project_data(self, project_id):
        """Get the project hierarchy and some metadata.

        This mimics the browser behaviour when opening the project editor. This
        will open a websocket connection to the server to get the informations.

        Args:
            project_id (str): The id of the project
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

        headers = {"Referer": url}
        headers.update(self.headers)
        with SocketIO(
            self.base_url,
            verify=self.verify,
            Namespace=Namespace,
            cookies={"sharelatex.sid": self.sharelatex_sid},
            headers=headers,
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

    def _request(self, verb, url, *args, **kwargs):
        headers = kwargs.get("headers", {})
        headers.update(self.headers)
        kwargs["headers"] = headers
        r = self.client.request(verb, url, *args, **kwargs)
        r.raise_for_status()
        return r

    def _get(self, url, *args, **kwargs):
        return self._request("GET", url, *args, **kwargs)

    def _post(self, url, *args, **kwargs):
        return self._request("POST", url, *args, **kwargs)

    def _delete(self, url, *args, **kwargs):
        return self._request("DELETE", url, *args, **kwargs)

    def download_project(self, project_id, *, path=".", keep_zip=False):
        """Download and unzip the project.

        Beware that this will overwrite any existing project file under path.

        Args:
            project_id (str): The id of the project to download
            path (Path): A valid path where the files will be saved

        Raises:
            Exception if the project can't be downloaded/unzipped.
        """
        url = f"{self.base_url}/project/{project_id}/download/zip"
        r = self._get(url, stream=True)
        logger.info(f"Downloading {project_id} in {path}")
        target_dir = Path(path)
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
        """Get a doc from a project .

        This mimics the browser behaviour when opening the project editor. This
        will open a websocket connection to the server to get the informations.

        Args:
            project_id (str): The id of the project
            doc_id (str): The id of the doc

        Returns:
            A string corresponding to the document.
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

        def on_connection_rejected(*args):
            logger.debug("[connectionRejected]  oh !!!")

        headers = {"Referer": url}
        headers.update(self.headers)
        with SocketIO(
            self.base_url,
            verify=self.verify,
            Namespace=Namespace,
            cookies={"sharelatex.sid": self.sharelatex_sid},
            headers=headers,
        ) as socketIO:

            def on_joint_doc(*args):
                storage.doc_data = args[1]

            def on_joint_project(*args):
                storage.project_data = args[1]
                socketIO.emit("joinDoc", doc_id, {"encodeRanges": True}, on_joint_doc)

            def on_connection_accepted(*args):
                logger.debug("[connectionAccepted]  Waoh !!!")
                socketIO.emit(
                    "joinProject", {"project_id": project_id}, on_joint_project
                )

            socketIO.on("connectionAccepted", on_connection_accepted)
            socketIO.on("connectionRejected", on_connection_rejected)
            socketIO.wait(seconds=3)
        # NOTE(msimonin): Check return type
        return "\n".join(storage.doc_data)

    def get_file(self, project_id, file_id):
        """Get an individual file (e.g image).

        Args:
            project_id (str): The project id of the project where the file is
            file_id (str): The file id

        Returns:
            requests response

        Raises:
            Exception if the file can't be downloaded
        """
        url = f"{self.base_url}/project/{project_id}/file/{file_id}"
        r = self._get(url, data=self.login_data, verify=self.verify)
        r.raise_for_status()
        # TODO(msimonin): return type
        return r

    def get_document(self, project_id, doc_id):
        """Get a single document (e.g tex file).

        Note: This method requires a patch server side to expose the
        corresponding endpoint. So one shouldn't use this in general

        Args:
            project_id (str): The project id of the project where the document 
                is
            doc_id (str): The document id

        Returns:
            requests response

        Raises:
            Exception if the file can't be downloaded
        """
        url = f"{self.base_url}/project/{project_id}/document/{doc_id}"
        r = self._get(url, data=self.login_data, verify=self.verify)

        # TODO(msimonin): return type
        return r

    def delete_file(self, project_id, file_id):
        """Delete a single file (e.g image).

        Args:
            project_id (str): The project id of the project where the file is
            file_id (str): The file id

        Returns:
            requests response

        Raises:
            Exception if the file can't be deleted
        """
        url = f"{self.base_url}/project/{project_id}/file/{file_id}"
        r = self._delete(url, data=self.login_data, verify=self.verify)
        r.raise_for_status()
        # TODO(msimonin): return type
        return r

    def delete_document(self, project_id, doc_id):
        """Delete a single document (e.g tex file).

        Args:
            project_id (str): The project id of the project where the document is
            doc_id (str): The document id

        Returns:
            requests response

        Raises:
            Exception if the file can't be deleted
        """
        url = f"{self.base_url}/project/{project_id}/doc/{doc_id}"
        r = self._delete(url, data=self.login_data, verify=self.verify)
        r.raise_for_status()
        # TODO(msimonin): return type

        return r

    def upload_file(self, project_id, folder_id, path):
        """Upload a file to sharelatex.

        Args:
            project_id (str): The project id
            folder_id (str): The parent folder
            path (str): Local path to the file

        Returns:
            requests response

        Raises:
            Exception if the file can't be uploaded
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
        r = self._post(url, params=params, files=files, verify=self.verify)
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
        r = self._post(url, data=data, verify=self.verify)
        r.raise_for_status()
        response = r.json()
        return response

    def check_or_create_folder(self, metadata, folder_path):
        """Check if a given folder exists on sharelatex side.

        Create it recursively if needed and return its id.
        It looks in the metadata and create the missing directories.
        Make sure the metadata are up-to-date when calling this.

        Args:
            metadata (dict): The sharelatex metadata as a structure basis
            folder_path (str): The folder path

        Returns:
            The folder id of the deepest folder created.
        """
        try:
            folder = lookup_folder(metadata, folder_path)
            return folder["folder_id"]
        except:
            logger.debug(f"{folder_path} not found, creation planed")

        parent_id = self.check_or_create_folder(metadata, os.path.dirname(folder_path))
        new_folder = self.create_folder(
            metadata["_id"], parent_id, os.path.basename(folder_path)
        )
        # This returns the id of the deepest folder
        return new_folder["_id"]

    def upload(self, path):
        """Upload a project (zip) to sharelatex.

        Args:
            path (str): Path to the zip file of a project.

        Returns:
             response (dict) status of the request as returned by sharelatex

        Raises:
             Exception if something is wrong with the zip of the upload.
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
        r = self._post(url, params=params, files=files, verify=self.verify)
        r.raise_for_status()
        response = r.json()
        if not response["success"]:
            raise Exception(f"Uploading {path} fails")
        return response

    def share(self, project_id, email, can_edit=True):
        """Send a invitation to share (edit/view) a project.

        Args:
            project_id (str): The project id of the project to share
            email (str): Email of the recipient of the invitation
            can_edit (boolean):True (resp. False) gives read/write (resp. read-only) access to the project 

        Returns:
            response (dict) status of the request as returned by sharelatex

        Raises:
             Exception if something is wrong with the compilation
        """
        url = f"{self.base_url}/project/{project_id}/invite"
        data = {
            "email": email,
            "privileges": "readAndWrite" if can_edit else "readOnly",
            "_csrf": self.csrf,
        }
        r = self._post(url, data=data, verify=self.verify)
        r.raise_for_status()
        response = r.json()
        return response

    def compile(self, project_id):
        """Trigger a remote compilation.

        Note that this is run against the remote version not the local one.

        Args:
            project_id (str): The project id of the project to compile

        Returns:
            response (dict) status of the request as returned by sharelatex

        Raises:
             Exception if something is wrong with the compilation
        """
        url = f"{self.base_url}/project/{project_id}/compile"

        data = {"_csrf": self.csrf}
        r = self._post(url, data=data, verify=self.verify)
        r.raise_for_status()
        response = r.json()
        if response["status"] != "success":
            raise CompilationError(response)
        return response

    def clone(self, project_id, project_name):
        """Copy a project.

        Args:
            project_id (str): The project id of the project to copy
            project_name (str): The project name of the destination project

        Returns:
            response (dict) containing the project_id of the created project

        Raises:
             Exception if something is wrong with the compilation
        """
        url = f"{self.base_url}/project/{project_id}/clone"

        data = {"_csrf": self.csrf, "projectName": project_name}
        r = self._post(url, data=data, verify=self.verify)
        r.raise_for_status()
        response = r.json()
        return response

    def new(self, project_name):
        """Create a new example project for the current user.

        Args:
            project_name (str): The project name of the project to create
        """
        url = f"{self.base_url}/project/new"

        data = {"_csrf": self.csrf, "projectName": project_name, "template": "example"}
        r = self._post(url, data=data, verify=self.verify)
        r.raise_for_status()
        response = r.json()
        return response

    def delete(self, project_id, *, forever=False):
        """Delete a project for the current user.

        Args:
            project_id (str): The project id of the project to delete
        """
        url = f"{self.base_url}/project/{project_id}"
        data = {"_csrf": self.csrf}
        params = {"forever": forever}
        r = self._delete(url, data=data, params=params, verify=self.verify)
        r.raise_for_status()
        return r
