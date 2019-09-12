from contextlib import contextmanager
import os
from sharelatex import SyncClient
from subprocess import check_call
import tempfile
import unittest


BASE_URL = os.environ.get("CI_BASE_URL")
USERNAME = os.environ.get("CI_USERNAME")
PASSWORD = os.environ.get("CI_PASSWORD")


def log(f):
    def wrapped(*args, **kwargs):
        print("-" * 60)
        print("{:^60}".format(f.__name__.upper()))
        print("-" * 60)
        return f(*args, **kwargs)

    return wrapped

class Project():
    
    def __init__(self, client, project_id, fs_path):
        self.client = client
        self.project_id = project_id
        self.fs_path = fs_path
        self.url = f"{BASE_URL}/project/{project_id}"


@contextmanager
def project(project_name):
    """A convenient contextmanager to create a temporary project on sharelatex."""
    client = SyncClient(base_url=BASE_URL, username=USERNAME, password=PASSWORD)
    with tempfile.TemporaryDirectory() as temp_path:
        os.chdir(temp_path)
        r = client.new(project_name)
        try:
            project_id = r["project_id"]
            fs_path = os.path.join(temp_path, project_id)
            # TODO(msimonin) yield the repo object also
            yield Project(client, project_id, fs_path)
        except Exception as e:
            raise e
        finally:
            client.delete(project_id, forever=True)


def new_project(f):
    """A convenient decorator to launch a function in the context of a new project."""

    def wrapped(*args, **kwargs):
        with project(f.__name__) as p:
            return f(*args, p, **kwargs)

    return wrapped


class TestCli(unittest.TestCase):

    @new_project
    def test_clone(self, project):
        check_call(
            f"git slatex clone {project.url} --username={USERNAME} --password={PASSWORD} --save-password",
            shell=True,
        )

    @new_project
    def test_clone_and_push(self, project):
        check_call(
            f"git slatex clone {project.url} --username={USERNAME} --password={PASSWORD} --save-password",
            shell=True,
        )
        os.chdir(project.fs_path)
        check_call("git slatex pull", shell=True)

