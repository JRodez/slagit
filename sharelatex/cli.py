import getpass
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Union
from zipfile import ZipFile
import datetime

import dateutil.parser

import click
import keyring
from git import Repo, Blob, Tree
from git.config import cp

from sharelatex import (
    SyncClient,
    get_authenticator_class,
    set_logger,
    walk_project_data,
)

logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
logger.setLevel(logging.INFO)
logger.addHandler(handler)

set_logger(logger)


def set_log_level(verbose=0):
    """set log level from interger value"""
    LOG_LEVELS = (logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG)
    logger.setLevel(LOG_LEVELS[verbose])


SLATEX_SECTION = "slatex"
SYNC_BRANCH = "__remote__sharelatex__"


def _commit_message(action):
    COMMIT_MESSAGE_BASE = "python-sharelatex "
    return COMMIT_MESSAGE_BASE + action


COMMIT_MESSAGE_PUSH = _commit_message("push")
COMMIT_MESSAGE_CLONE = _commit_message("clone")
COMMIT_MESSAGE_PREPULL = _commit_message("pre pull")
COMMIT_MESSAGE_UPLOAD = _commit_message("upload")
COMMIT_MESSAGES = [
    COMMIT_MESSAGE_PUSH,
    COMMIT_MESSAGE_CLONE,
    COMMIT_MESSAGE_PREPULL,
    COMMIT_MESSAGE_UPLOAD,
]

MESSAGE_REPO_ISNT_CLEAN = "The repo isn't clean."

PROMPT_BASE_URL = "Base url: "
PROMPT_PROJECT_ID = "Project id: "
PROMPT_AUTH_TYPE = "Authentification type (*gitlab*|community|legacy): "
DEFAULT_AUTH_TYPE = "gitlab"
PROMPT_USERNAME = "Username: "
PROMPT_PASSWORD = "Password: "
PROMPT_CONFIRM = "Do you want to save your password in your OS keyring system (y/n) ?"
MAX_NUMBER_ATTEMPTS = 3


class Config:
    """Handle gitconfig read/write operations in a transparent way."""

    def __init__(self, repo):
        self.repo = repo
        self.keyring = keyring.get_keyring()

    def get_password(self, service, username):
        return self.keyring.get_password(service, username)

    def set_password(self, service, username, password):
        self.keyring.set_password(service, username, password)

    def delete_password(self, service, username):
        self.keyring.delete_password(service, username)

    def set_value(self, section, key, value, config_level="repository"):
        """Set a config value in a specific section.

        Note:
            If the section doesn't exist it is created.

        Args:
            section (str): the section name
            key (str): the key to set
            value (str): the value to set
        """
        with self.repo.config_writer(config_level) as c:
            try:
                c.set_value(section, key, value)
            except cp.NoSectionError as e:
                # No section is found, we create a new one
                logger.debug(e)
                c.set_value(section, "init", "")
            except Exception as e:
                raise e
            finally:
                c.release()

    def get_value(self, section, key, default=None, config_level=None):
        """Get a config value in a specific section of the config.

                Note: this returns the associated value if found.
                      Otherwise it returns the default value.

                Args:
                    section (str): the section name: str
                    key (str): the key to set
                    default (str): the defaut value to apply
                    config_level (str): the config level to look for
                    see:
        https://gitpython.readthedocs.io/en/stable/reference.html#git.repo.base.Repo.config_level

        """
        with self.repo.config_reader(config_level) as c:
            try:
                value = c.get_value(section, key)
            except cp.NoSectionError as e:
                logger.debug(e)
                value = default
            except cp.NoOptionError as e:
                logger.debug(e)
                value = default
            except Exception as e:
                raise e
            finally:
                return value


def get_clean_repo(path=None):
    """Create the git.repo object from a directory.

    Note:

        This initialize the git repository and fails if the repo isn't clean.
        This is run prior to many operations to make sure there isn't any
        untracked/uncomitted files in the repo.

    Args:
        path (str): the path of the repository in the local file system.

    Returns:
        a git.Repo data-structure.

    Raises:
        Exception if the repo isn't clean
    """
    repo = Repo.init(path=path)
    # Fail if the repo is clean
    if repo.is_dirty(index=True, working_tree=True, untracked_files=True):
        logger.error(repo.git.status())
        raise Exception(MESSAGE_REPO_ISNT_CLEAN)
    return repo


def refresh_project_information(
    repo, base_url=None, project_id=None, https_cert_check=None
):
    """Get and/or set the project information in/from the git config.

    If the information is set in the config it is retrieved, otherwise it is set.

    Args:
        repo (git.Repo): The repo object to read the config from
        base_url (str): the base_url to consider
        project_id (str): the project_id to consider

    Returns:
        tuple (base_url, project_id) after the refresh occurs.
    """
    config = Config(repo)
    if base_url is None:
        u = config.get_value(SLATEX_SECTION, "baseUrl")
        if u is not None:
            base_url = u
        else:
            base_url = input(PROMPT_BASE_URL)
            config.set_value(SLATEX_SECTION, "baseUrl", base_url)
    else:
        config.set_value(SLATEX_SECTION, "baseUrl", base_url)
    if project_id is None:
        p = config.get_value(SLATEX_SECTION, "projectId")
        if p is not None:
            project_id = p
        else:
            project_id = input(PROMPT_PROJECT_ID)
        config.set_value(SLATEX_SECTION, "projectId", project_id)
    else:
        config.set_value(SLATEX_SECTION, "projectId", project_id)
    if https_cert_check is None:
        c = config.get_value(SLATEX_SECTION, "httpsCertCheck")
        if c is not None:
            https_cert_check = c
        else:
            https_cert_check = True
            config.set_value(SLATEX_SECTION, "httpsCertCheck", https_cert_check)
    else:
        config.set_value(SLATEX_SECTION, "httpsCertCheck", https_cert_check)

    return base_url, project_id, https_cert_check


def refresh_account_information(
    repo,
    auth_type,
    username=None,
    password=None,
    save_password=None,
    ignore_saved_user_info=False,
):
    """Get and/or set the account information in/from the git config.

    If the information is set in the config it is retrieved, otherwise it is set.
    Note that no further encryption of the password is offered here.

    Args:
        repo (git.Repo): The repo object to read the config from
        username (str): The username to consider
        password (str): The password to consider
        save_password (boolean): True for save user account information (in OS
                                 keyring system) if needed
        ignore_saved_user (boolean): True for ignore user account information (in
                                 OS keyring system) if present
    Returns:
        tuple (login_path, username, password) after the refresh occurs.
    """

    config = Config(repo)
    base_url = config.get_value(SLATEX_SECTION, "baseUrl")
    if auth_type is None:
        if not ignore_saved_user_info:
            u = config.get_value(SLATEX_SECTION, "authType")
            if u:
                auth_type = u
    if auth_type is None:
        auth_type = input(PROMPT_AUTH_TYPE)
        if not auth_type:
            auth_type = DEFAULT_AUTH_TYPE
    config.set_value(SLATEX_SECTION, "authType", auth_type)

    if username is None:
        if not ignore_saved_user_info:
            u = config.get_value(SLATEX_SECTION, "username")
            if u:
                username = u
    if username is None:
        username = input(PROMPT_USERNAME)
    config.set_value(SLATEX_SECTION, "username", username)

    if password is None:
        if not ignore_saved_user_info:
            p = config.get_password(base_url, username)
            if p:
                password = p
    if password is None:
        password = getpass.getpass(PROMPT_PASSWORD)
        if save_password is None:
            r = input(PROMPT_CONFIRM)
            if r == "Y" or r == "y":
                save_password = True
    if save_password:
        config.set_password(base_url, username, password)
    return auth_type, username, password


def getClient(
    repo,
    base_url,
    auth_type,
    username,
    password,
    verify,
    save_password=None,
):
    logger.info(f"try to open session on {base_url} with {username}")
    client = None

    authenticator = get_authenticator_class(auth_type)()
    for i in range(MAX_NUMBER_ATTEMPTS):
        try:
            client = SyncClient(
                base_url=base_url,
                username=username,
                password=password,
                verify=verify,
                authenticator=authenticator,
            )
        except Exception as inst:
            client = None
            logger.warning("{}  : attempt # {} ".format(inst, i + 1))
            auth_type, username, password = refresh_account_information(
                repo,
                auth_type,
                save_password=save_password,
                ignore_saved_user_info=True,
            )
    if client is None:
        raise Exception("maximum number of authentication attempts is reached")
    return client


def update_ref(repo, message="update_ref"):
    """Makes the remote pointer to point on the latest revision we have.

    This is called after a successfull clone, push, new. In short when we
    are sure the remote and the local are in sync.
    """
    git = repo.git

    git.add(".")
    # with this we can have two consecutive commit with the same content
    repo.index.commit(f"{message}")
    sync_branch = repo.create_head(SYNC_BRANCH, force=True)
    sync_branch.commit = "HEAD"


@click.group()
def cli():
    pass


def log_options(function):
    function = click.option(
        "-v",
        "--verbose",
        count=True,
        default=2,
        help="verbose level (can be: -v, -vv, -vvv)",
    )(function)
    function = click.option("-s", "--silent", "verbose", flag_value=0)(function)
    function = click.option("--debug", "-d", "verbose", flag_value=3)(function)
    return function


def authentication_options(function):
    function = click.option(
        "--auth_type",
        "-a",
        default=None,
        help="""Authentification type (gitlab|community|legacy).""",
    )(function)

    function = click.option(
        "--username",
        "-u",
        default=None,
        help="""Username for sharelatex server account, if username is not provided,
 it will be asked online""",
    )(function)
    function = click.option(
        "--password",
        "-p",
        default=None,
        help="""User password for sharelatex server, if password is not provided,
 it will be asked online""",
    )(function)
    function = click.option(
        "--save-password/--no-save-password",
        default=None,
        help="""Save user account information (in OS keyring system)""",
    )(function)
    function = click.option(
        "--ignore-saved-user-info",
        default=False,
        help="""Forget user account information already saved (in OS keyring system)""",
    )(function)

    return function


@cli.command(help="test log levels")
@log_options
def test(verbose):
    set_log_level(verbose)
    logger.debug("debug")
    logger.info("info")
    logger.error("error")
    logger.warning("warning")
    print("print")


def _sync_deleted_items(
    working_path: Path, remote_items: Dict[Any, Any], objetcs: List[Union[Blob, Tree]]
):
    remote_path = [Path(fd["folder_path"]).joinpath(fd["name"]) for fd in remote_items]
    for blob_path in objetcs:
        p_relative = blob_path.relative_to(working_path)
        # check the path and all of its parents dir
        if p_relative not in remote_path:
            logger.debug(f"delete {blob_path}")
            if blob_path.is_dir():
                blob_path.rmdir()
            else:
                Path.unlink(blob_path)


def _get_datetime_from_git(repo, branch, files, working_path):
    datetimes_dict = {}
    for p in files:
        commits = repo.iter_commits(branch)
        p_relative = p.relative_to(working_path)
        if not str(p_relative).startswith(".git"):
            if p not in datetimes_dict:
                for c in commits:
                    re = repo.git.show("--pretty=", "--name-only", c.hexsha)
                    if re != "":
                        commit_file_list = re.split("\n")
                        for cf in commit_file_list:
                            if cf not in datetimes_dict:
                                datetimes_dict[cf] = c.authored_datetime
                        if p in datetimes_dict:
                            break
    return datetimes_dict


def _sync_remote_files(client, project_id, working_path, remote_items, datetimes_dict):
    remote_files = (item for item in remote_items if item["type"] == "file")
    # TODO: build the list of file to download and then write them in a second step
    logger.debug("check if remote files are newer that locals")
    for remote_file in remote_files:
        need_to_download = False
        local_path = working_path.joinpath(remote_file["folder_path"]).joinpath(
            remote_file["name"]
        )
        relative_path = str(
            Path(remote_file["folder_path"]).joinpath(remote_file["name"])
        )
        if local_path.is_file():

            if relative_path in datetimes_dict:
                local_time = datetimes_dict[relative_path]
            else:
                local_time = datetime.datetime.fromtimestamp(
                    local_path.stat().st_mtime, datetime.timezone.utc
                )
            remote_time = dateutil.parser.parse(remote_file["created"])
            logger.debug(f"local time for {local_path} : {local_time}")
            logger.debug(f"remote time for {local_path} : {remote_time}")
            if local_time < remote_time:
                need_to_download = True
        else:
            need_to_download = True
        if need_to_download:
            logger.info(f"download from server file to update {local_path}")
            client.get_file(project_id, remote_file["_id"], dest_path=local_path)
            # TODO: set local time for downloaded file to remote_time


def _sync_remote_docs(
    client, project_id, working_path, remote_items, update_data, datetimes_dict
):
    remote_docs = (item for item in remote_items if item["type"] == "doc")
    logger.debug("check if remote documents are newer that locals")
    for remote_doc in remote_docs:
        doc_id = remote_doc["_id"]
        need_to_download = False
        local_path = working_path.joinpath(remote_doc["folder_path"]).joinpath(
            remote_doc["name"]
        )
        relative_path = str(
            Path(remote_doc["folder_path"]).joinpath(remote_doc["name"])
        )
        if local_path.is_file():
            if relative_path in datetimes_dict:
                local_time = datetimes_dict[relative_path]
            else:
                local_time = datetime.datetime.fromtimestamp(
                    local_path.stat().st_mtime, datetime.timezone.utc
                )
            updates = [
                update["meta"]["end_ts"]
                for update in update_data["updates"]
                if doc_id in update["docs"]
            ]
            if len(updates) > 0:
                remote_time = datetime.datetime.fromtimestamp(
                    updates[0] / 1000, datetime.timezone.utc
                )
                logger.debug(f"local time for {local_path} : {local_time}")
                logger.debug(f"remote time for {local_path} : {remote_time}")
                if local_time < remote_time:
                    need_to_download = True
            # elif not local_path.is_file():
            #     remote_time = datetime.datetime.now(datetime.timezone.utc)
        else:
            logger.debug(f"local path {local_path} is missing, need to download")
            need_to_download = True
        if need_to_download:
            logger.info(f"download from server file to update {local_path}")
            client.get_document(project_id, doc_id, dest_path=local_path)
        # TODO: set local time for downloaded document to remote_time


def _pull(repo, client, project_id):
    # attempt to "merge" the remote and the local working copy

    git = repo.git
    active_branch = repo.active_branch.name
    git.checkout(SYNC_BRANCH)
    working_path = Path(repo.working_tree_dir)
    logger.debug("find last commit using remote server")
    # for optimization purpose
    for commit in repo.iter_commits():
        if commit.message in COMMIT_MESSAGES:
            logger.debug(f"find this : {commit.message} -- {commit.hexsha}")
            break
    logger.debug(
        f"commit as reference for upload updates: {commit.message} -- {commit.hexsha}"
    )
    # mode détaché
    git.checkout(commit)

    try:
        # etat du serveur actuel
        data = client.get_project_data(project_id)
        remote_items = [item for item in walk_project_data(data)]
        # état (supposé) du serveur la dernière fois qu'on s'est synchronisé
        # on ne prend en compte que les fichier trackés par git
        # https://gitpython.readthedocs.io/en/stable/tutorial.html#the-tree-object
        objects = [Path(b.abspath) for b in repo.head.commit.tree.traverse()]
        objects.reverse()

        datetimes_dict = _get_datetime_from_git(
            repo, SYNC_BRANCH, objects, working_path
        )

        _sync_deleted_items(working_path, remote_items, objects)

        _sync_remote_files(
            client, project_id, working_path, remote_items, datetimes_dict
        )

        update_data = client.get_project_update_data(project_id)
        # TODO: change de file time stat for the corresponding time in server
        _sync_remote_docs(
            client, project_id, working_path, remote_items, update_data, datetimes_dict
        )

        # TODO reset en cas d'erreur ?
        # on se place sur la branche de synchro
        git.checkout(SYNC_BRANCH)
    except Exception as e:
        # hard reset ?
        git.reset("--hard")
        git.checkout(active_branch)
        raise e
    if repo.is_dirty(index=True, working_tree=True, untracked_files=True):
        diff_index = repo.index.diff(None)
        logger.debug(
            f"""Modified files in server :
            {[d.a_path for d in diff_index.iter_change_type("M")]}"""
        )
        logger.debug(
            f"""New files in server :
            {[d.a_path for d in diff_index.iter_change_type("A")]}"""
        )
        logger.debug(
            f"""deleted files in server :
            {[d.a_path for d in diff_index.iter_change_type("D")]}"""
        )
        logger.debug(
            f"""renamed files in server :
            {[d.a_path for d in diff_index.iter_change_type("R")]}"""
        )
        logger.debug(
            f"""Path type changed in server:
            {[d.a_path for d in diff_index.iter_change_type("T")]}"""
        )
        update_ref(repo, message=COMMIT_MESSAGE_PREPULL)
    git.checkout(active_branch)
    git.merge(SYNC_BRANCH)


@cli.command(help="Compile the remote version of a project")
@click.argument("project_id", default="")
@authentication_options
@log_options
def compile(
    project_id,
    auth_type,
    username,
    password,
    save_password,
    ignore_saved_user_info,
    verbose,
):
    set_log_level(verbose)
    repo = Repo()
    base_url, project_id, https_cert_check = refresh_project_information(repo)
    auth_type, username, password = refresh_account_information(
        repo, auth_type, username, password, save_password, ignore_saved_user_info
    )
    client = getClient(
        repo,
        base_url,
        auth_type,
        username,
        password,
        https_cert_check,
        save_password,
    )

    response = client.compile(project_id)
    logger.debug(response)


@cli.command(help="Send a invitation to share (edit/view) a project")
@click.argument("email", default="")
@click.option("--project_id", default=None)
@click.option(
    "--can-edit/--read-only",
    default=True,
    help="""Authorize user to edit the project or not""",
)
@authentication_options
@log_options
def share(
    project_id,
    email,
    can_edit,
    auth_type,
    username,
    password,
    save_password,
    ignore_saved_user_info,
    verbose,
):
    set_log_level(verbose)
    repo = Repo()
    base_url, project_id, https_cert_check = refresh_project_information(
        repo, project_id=project_id
    )
    auth_type, username, password = refresh_account_information(
        repo, auth_type, username, password, save_password, ignore_saved_user_info
    )
    client = getClient(
        repo,
        base_url,
        auth_type,
        username,
        password,
        https_cert_check,
        save_password,
    )

    response = client.share(project_id, email, can_edit)
    logger.debug(response)


@cli.command(
    help=f"""Pull the files from sharelatex.

    In the current repository, it works as follows:

    1. Pull in ``{SYNC_BRANCH}`` branch the latest version of the remote project\n
    2. Attempt a merge in the working branch. If the merge can't be done automatically,
       you will be required to fix the conflict manually
    """
)
@authentication_options
@log_options
def pull(
    auth_type,
    username,
    password,
    save_password,
    ignore_saved_user_info,
    verbose,
):
    set_log_level(verbose)

    # Fail if the repo is not clean
    repo = get_clean_repo()
    base_url, project_id, https_cert_check = refresh_project_information(repo)
    auth_type, username, password = refresh_account_information(
        repo, auth_type, username, password, save_password, ignore_saved_user_info
    )
    client = getClient(
        repo,
        base_url,
        auth_type,
        username,
        password,
        https_cert_check,
        save_password,
    )
    _pull(repo, client, project_id)


@cli.command(
    help=f"""
Get (clone) the files from sharelatex projet URL and create a local git depot.

The optional target directory will be created if it doesn't exist. The command
fails if it already exists. Connection information can be saved in the local git
config.

It works as follow:

    1. Download and unzip the remote project in the target directory\n
    2. Initialize a fresh git repository\n
    3. Create an extra ``{SYNC_BRANCH}`` to keep track of the remote versions of
       the project. This branch must not be updated manually.
"""
)
@click.argument(
    "projet_url", default=""
)  # , help="The project url (https://sharelatex.irisa.fr/1234567890)")
@click.argument("directory", default="")  # , help="The target directory")
@click.option(
    "--https-cert-check/--no-https-cert-check",
    default=True,
    help="""force to check https certificate or not""",
)
@authentication_options
@log_options
def clone(
    projet_url,
    directory,
    auth_type,
    username,
    password,
    save_password,
    ignore_saved_user_info,
    https_cert_check,
    verbose,
):
    set_log_level(verbose)
    # TODO : robust parse regexp
    slashparts = projet_url.split("/")
    project_id = slashparts[-1]
    base_url = "/".join(slashparts[:-2])
    if base_url == "":
        raise Exception("projet_url is not well formed or missing")
    if directory == "":
        directory = Path(os.getcwd())
        directory = Path(directory, project_id)
    else:
        directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)

    repo = get_clean_repo(path=directory)

    base_url, project_id, https_cert_check = refresh_project_information(
        repo, base_url, project_id, https_cert_check
    )
    auth_type, username, password = refresh_account_information(
        repo, auth_type, username, password, save_password, ignore_saved_user_info
    )

    try:
        client = getClient(
            repo,
            base_url,
            auth_type,
            username,
            password,
            https_cert_check,
            save_password,
        )
    except Exception as inst:
        import shutil

        shutil.rmtree(directory)
        raise inst
    client.download_project(project_id, path=directory)
    # TODO(msimonin): add a decent default .gitignore ?
    update_ref(repo, message=COMMIT_MESSAGE_CLONE)


@cli.command(
    help="""Synchronize the local copy with the remote version.

This works as follow:

1. The remote version is pulled (see the :program:`pull` command)\n
2. After the merge succeed, the merged version is uploaded back to the remote server.\n
   Note that only the files that have changed (modified/added/removed) will be uploaded.
"""
)
@click.option("--force", is_flag=True, help="Force push")
@authentication_options
@log_options
def push(
    force,
    auth_type,
    username,
    password,
    save_password,
    ignore_saved_user_info,
    verbose,
):
    set_log_level(verbose)

    def _upload(client, project_data, path):
        # initial factorisation effort
        path = Path(path)
        logger.debug(f"Uploading {path}")
        project_id = project_data["_id"]
        folder_id = client.check_or_create_folder(project_data, path.parent)
        p = Path(repo.working_dir).joinpath(path)
        client.upload_file(project_id, folder_id, str(p))

    def _delete(client, project_data, path):
        # initial factorisation effort
        path = Path(path)
        logger.debug(f"Deleting {path}")
        project_id = project_data["_id"]
        entities = walk_project_data(
            project_data,
            lambda x: Path(x["folder_path"]) == path.parent and x["name"] == path.name,
        )
        # there should be one
        entity = next(entities)
        if entity["type"] == "doc":
            client.delete_document(project_id, entity["_id"])
        elif entity["type"] == "file":
            client.delete_file(project_id, entity["_id"])

    repo = get_clean_repo()
    base_url, project_id, https_cert_check = refresh_project_information(repo)
    auth_type, username, password = refresh_account_information(
        repo, auth_type, username, password, save_password, ignore_saved_user_info
    )

    client = getClient(
        repo,
        base_url,
        auth_type,
        username,
        password,
        https_cert_check,
        save_password,
    )

    if not force:
        _pull(repo, client, project_id)

    master_commit = repo.commit("HEAD")
    sync_commit = repo.commit(SYNC_BRANCH)
    diff_index = sync_commit.diff(master_commit)

    project_data = client.get_project_data(project_id)

    logger.debug("Modify files to upload :")
    for d in diff_index.iter_change_type("M"):
        _upload(client, project_data, d.a_path)

    logger.debug("new files to upload :")
    for d in diff_index.iter_change_type("A"):
        _upload(client, project_data, d.a_path)

    logger.debug("delete files :")
    for d in diff_index.iter_change_type("D"):
        _delete(client, project_data, d.a_path)

    logger.debug("rename files :")
    for d in diff_index.iter_change_type("R"):
        # git mv a b
        # for us this corresponds to
        # 1) deleting the old one (a)
        # 2) creating the new one (b)
        _delete(client, project_data, d.a_path)
        _upload(client, project_data, d.b_path)
    logger.debug("Path type changes :")
    for d in diff_index.iter_change_type("T"):
        # This one is maybe
        # 1) deleting the old one (a)
        # 2) creating the new one (b)
        _delete(client, project_data, d.a_path)
        _upload(client, project_data, d.b_path)
    if repo.is_dirty(index=True, working_tree=True, untracked_files=True):
        update_ref(repo, message=COMMIT_MESSAGE_PUSH)


@cli.command(
    help="""
Upload the current directory as a new sharelatex project.

This litteraly creates a new remote project in sync with the local version.
"""
)
@click.argument("projectname")
@click.argument("base_url")
@click.option(
    "--https-cert-check/--no-https-cert-check",
    default=True,
    help="""force to check https certificate or not""",
)
@authentication_options
@log_options
def new(
    projectname,
    base_url,
    https_cert_check,
    auth_type,
    username,
    password,
    save_password,
    ignore_saved_user_info,
    verbose,
):
    set_log_level(verbose)
    repo = get_clean_repo()

    refresh_project_information(repo, base_url, "NOT SET", https_cert_check)
    auth_type, username, password = refresh_account_information(
        repo, auth_type, username, password, save_password, True
    )
    client = getClient(
        repo,
        base_url,
        auth_type,
        username,
        password,
        https_cert_check,
        save_password,
    )

    iter_file = repo.tree().traverse()

    with tempfile.TemporaryDirectory() as tmp:
        archive_name = os.path.join(tmp, f"{projectname}.zip")
        with ZipFile(archive_name, "w") as z:
            for f in iter_file:
                logger.debug(f"Adding {f.path} to the archive")
                z.write(f.path)

        response = client.upload(archive_name)
        logger.info(
            "Successfully uploaded %s [%s]" % (projectname, response["project_id"])
        )

        refresh_project_information(
            repo, base_url, response["project_id"], https_cert_check
        )
        update_ref(repo, message="upload")
