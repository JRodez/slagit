import json
import logging
import os
from pathlib import Path
import time

import getpass

from sharelatex import SyncClient, walk_files, walk_project_data


import click
from git import Repo
from git.config import cp
from zipfile import ZipFile

logger = logging.getLogger(__name__)
SHARELATEX_FILE = ".sharelatex"
SLATEX_SECTION = "slatex"
SYNC_BRANCH = "__remote__sharelatex__"


logging.basicConfig(level=logging.DEBUG)


@click.group()
def cli():
    pass


class Config:
    """Handle gitconfig read/write operations in a transparent way."""

    def __init__(self, repo):
        self.repo = repo

    def set_value(self, section, key, value, config_level="repository"):
        with self.repo.config_writer(config_level) as c:
            try:
                c.set_value(section, key, value)
            except cp.NoSectionError as e:
                # No section is found, we create a new one
                logging.debug(e)
                c.set_value(SLATEX_SECTION, "init", "")
            except Exception as e:
                raise e
            finally:
                c.release()

    def get_value(self, section, key, default=None, config_level=None):
        with self.repo.config_reader(config_level) as c:
            try:
                value = c.get_value(section, key)
            except cp.NoSectionError as e:
                logging.debug(e)
                value = default
            except cp.NoOptionError as e:
                logging.debug(e)
                value = default
            except Exception as e:
                raise e
            finally:
                return value


def get_clean_repo(path=None):
    repo = Repo.init(path=path)
    # Fail if the repo is clean
    if repo.is_dirty(index=True, working_tree=True, untracked_files=True):
        print(repo.git.status())
        raise Exception("The repo isn't clean")
    return repo


def refresh_project_information(repo, base_url=None, project_id=None):
    need_save = True
    config = Config(repo)
    if base_url == None:
        #            u = reader.get_value(SLATEX_SECTION, "baseUrl")
        u = config.get_value(SLATEX_SECTION, "baseUrl")
        if u:
            base_url = u
            need_save = False
        else:
            base_url = input("base url :")
            need_save = True
    if project_id == None:
        p = config.get_value(SLATEX_SECTION, "projectId")
        if p:
            project_id = p
            need_save = False
        else:
            project_id = input("project id :")
            need_save = True
    if need_save:
        config.set_value("slatex", "baseUrl", base_url)
        config.set_value("slatex", "projectId", project_id)
    return base_url, project_id


def refresh_account_information(repo, username=None, password=None, save_password=None):
    need_save = True
    config = Config(repo)
    if username == None:
        u = config.get_value(SLATEX_SECTION, "username")
        if u:
            username = u
            need_save = False
        else:
            username = input("username :")
            need_save = True
    if password == None:
        p = config.get_value(SLATEX_SECTION, "password")
        if p:
            password = p
            need_save = False
        else:
            password = getpass.getpass("password:")
            if save_password == None:
                r = input(
                    "do you want to save in git config (in clair) your password (y/n) ?"
                )
                if r == "Y" or r == "y":
                    save_password = True
            need_save = True
    if save_password and need_save:
        config.set_value(SLATEX_SECTION, "username", username)
        config.set_value(SLATEX_SECTION, "password", password)
    return username, password


def update_ref(repo, message="update_ref"):
    git = repo.git

    git.add(".")
    # with this we can have two consecutive commit with the same content
    repo.index.commit(f"{message}")
    sync_branch = repo.create_head(SYNC_BRANCH, force=True)
    sync_branch.commit = "HEAD"


def _pull(repo, client, project_id):
    if repo.is_dirty(index=True, working_tree=True, untracked_files=True):
        print(repo.git.status())
        print("The repository isn't clean")
        return

    # attempt to "merge" the remote and the local working copy

    # TODO(msimonin) get current branch
    # here we assume master
    git = repo.git
    git.checkout(SYNC_BRANCH)

    # delete all files but not .git !!!!
    files = list(Path(repo.working_tree_dir).rglob("*"))
    files.reverse()
    for p in files:
        if not str(p.relative_to(Path(repo.working_tree_dir))).startswith(".git"):
            if p.is_dir():
                p.rmdir()
            else:
                Path.unlink(p)

    # TODO: try to check directly from server what file or directory
    # is changed/delete/modify instead to reload whole project zip

    client.download_project(project_id)
    update_ref(repo, message="pre pull")
    git.checkout("master")
    git.merge(SYNC_BRANCH)


@cli.command(help="Compile the remote version of a project")
@click.argument("project_id", default="")
def compile(project_id):
    repo = Repo()
    base_url, project_id = refresh_project_information(repo)
    username, password = refresh_account_information(repo)
    client = SyncClient(
        base_url=base_url, username=username, password=password, verify=True
    )

    response = client.compile(project_id)
    print(response)


@cli.command(
    help="""
Pull the files from sharelatex.
(Note this uses the current directory)
"""
)
def pull():
    repo = Repo()
    base_url, project_id = refresh_project_information(repo)
    username, password = refresh_account_information(repo)
    client = SyncClient(
        base_url=base_url, username=username, password=password, verify=True
    )
    # Fail if the repo is clean
    _pull(repo, client, project_id)

    # TODO(msimonin): add a decent default .gitignore ?
    # update_ref(repo, message="pull")


@cli.command(
    help="""
Get (clone) the files from sharelatex projet URL and crate a local git depot.
(Note this uses the current directory)
"""
)
@click.argument("projet_url", default="")
@click.argument("directory", default="")
@click.option(
    "--username",
    "-u",
    default=None,
    help="""username for sharelatex server account, if user is not provided, it will be asked online""",
)
@click.option(
    "--password",
    "-p",
    default=None,
    help="""user password for sharelatex server, if password is not provided, it will be asked online""",
)
@click.option(
    "--save-password/--no-save-password",
    default=None,
    help="""save user account information (clear password) in git local config""",
)
def clone(projet_url, directory, username, password, save_password):
    # TODO : robust parse regexp
    slashparts = projet_url.split("/")
    project_id = slashparts[-1]
    base_url = "/".join(slashparts[:-2])

    if directory == "":
        directory = Path(os.getcwd())
        directory = Path(directory, project_id)
    else:
        directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    repo = get_clean_repo(path=directory)
    username, password = refresh_account_information(
        repo, username, password, save_password
    )

    base_url, project_id = refresh_project_information(repo, base_url, project_id)

    client = SyncClient(
        base_url=base_url, username=username, password=password, verify=True
    )

    client.download_project(project_id, path=directory)
    # TODO(msimonin): add a decent default .gitignore ?
    update_ref(repo, message="clone")


@cli.command(help="Push the commited changes back to sharelatex")
@click.option(
    "--force",
    "-f",
    help="""Push without attempting to resync
the remote project with the local""",
)
def push(force):
    repo = get_clean_repo()
    base_url, project_id = refresh_project_information(repo)
    username, password = refresh_account_information(repo)
    client = SyncClient(
        base_url=base_url, username=username, password=password, verify=True
    )
    if not force:
        _pull(repo, client, project_id)

    master_commit = repo.commit("master")
    sync_commit = repo.commit(SYNC_BRANCH)
    diff_index = sync_commit.diff(master_commit)

    project_data = client.get_project_data(project_id)
    logging.debug("Modify files to upload :")
    for d in diff_index.iter_change_type("M"):
        logging.debug(d.a_path)
        dirname = os.path.dirname(d.a_path)
        # TODO: that smells
        dirname = "/" + dirname
        basename = os.path.basename(d.a_path)
        entities = walk_project_data(
            project_data,
            lambda x: x["folder_path"] == dirname and x["name"] == basename,
        )
        entity = next(entities)
        path = f"{repo.working_dir}{entity['folder_path']}/{entity['name']}"
        client.upload_file(project_id, entity["folder_id"], path)
    logging.debug("new files to upload :")
    for d in diff_index.iter_change_type("A"):
        logging.debug(d.a_path)
        dirname = os.path.dirname(d.a_path)
        # TODO: that smells
        dirname = "/" + dirname
        # TODO encapsulate both ?
        folder_id = client.check_or_create_folder(project_data, dirname)
        path = f"{repo.working_dir}/{d.a_path}"
        client.upload_file(project_id, folder_id, path)
    logging.debug("delete files :")
    for d in diff_index.iter_change_type("D"):
        logging.debug(f"d.a_path={d.a_path}")
        dirname = os.path.dirname(d.a_path)
        # TODO: that smells
        dirname = "/" + dirname
        basename = os.path.basename(d.a_path)
        entities = walk_project_data(
            project_data,
            lambda x: x["folder_path"] == dirname and x["name"] == basename,
        )
        entity = next(entities)
        if entity["type"] == "doc":
            client.delete_document(project_id, entity["_id"])
        elif entity["type"] == "file":
            client.delete_file(project_id, entity["_id"])
    logging.debug("reanme files :")
    for d in diff_index.iter_change_type("R"):
        logging.debug(d.a_path)
    logging.debug("Path type changes :")
    for d in diff_index.iter_change_type("T"):
        logging.debug(d.a_path)

    # First iteration, we push we have in the project data
    # limitations: modification on the local tree (folder, file creation) will
    # not be propagated

    # iter = walk_files(project_data)
    # for i in iter:
    #     # the / at the beginnning of i["folder_path"] makes the join to forget
    #     # about the working dir
    #     # path = os.path.join(repo.working_dir, i["folder_path"], i["name"])
    #     path = f"{repo.working_dir}{i['folder_path']}/{i['name']}"
    #     client.upload_file(project_id, i["folder_id"], path)

    update_ref(repo, message="push")


@cli.command(help="Upload the current directory as a new sharelatex project")
@click.argument("projectname")
@click.argument("base_url")
@click.option(
    "--username",
    "-u",
    default=None,
    help="""username for sharelatex server account, if user is not provided, it will be asked online""",
)
@click.option(
    "--password",
    "-p",
    default=None,
    help="""user password for sharelatex server, if password is not provided, it will be asked online""",
)
@click.option(
    "--save-password/--no-save-password",
    default=None,
    help="""save user account information (clear password) in git local config""",
)
def new(projectname, base_url, username, password, save_password):
    repo = get_clean_repo()
    username, password = refresh_account_information(
        repo, username, password, save_password
    )

    client = SyncClient(
        base_url=base_url, username=username, password=password, verify=True
    )
    iter_file = repo.tree().traverse()
    archive_name = "%s.zip" % projectname
    archive_path = Path(archive_name)
    with ZipFile(str(archive_path), "w") as z:
        for f in iter_file:
            logging.debug(f"Adding {f.path} to the archive")
            z.write(f.path)

    response = client.upload(archive_name)
    print("Successfully uploaded %s [%s]" % (projectname, response["project_id"]))
    archive_path.unlink()

    refresh_project_information(repo, base_url, response["project_id"])
    update_ref(repo, message="upload")
