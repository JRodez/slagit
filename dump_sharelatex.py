import re
import getpass
import os
import requests
import zipfile


BASE_URL = "https://sharelatex.irisa.fr"
LOGIN_URL = "{}/login".format(BASE_URL)
print("email: ")
EMAIL = input()
PASSWORD = getpass.getpass()



def init_client():
    client = requests.session()

    # Retrieve the CSRF token first
    r = client.get(LOGIN_URL, verify=False)
    csrftoken = re.search('(?<=csrfToken = ").{36}', r.text).group(0)
    # login
    login_data = {"email": EMAIL,
                "password": PASSWORD,
                "_csrf":csrftoken}
    return client, login_data


def browse_project(client,login_data, project_id, path='.'):
    r = client.post(LOGIN_URL, data=login_data, verify=False)
    project_url= "{base}/project/{pid}".format(base=BASE_URL,
                                                pid=project_id)

def download_project(client,login_data,project_id, path='.'):
    zip_url = "{base}/project/{pid}/download/zip".format(base=BASE_URL,
                                                         pid=project_id)

    r = client.post(LOGIN_URL, data=login_data, verify=False)
    r = client.get(zip_url, stream=True)

    print("Downloading")
    target_path = os.path.join(path, "{}.zip".format(project_id))
    with open(target_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024):
            if chunk:
                f.write(chunk)

    print("Unzipping ....")
    zip_file = zipfile.ZipFile(target_path)
    zip_file.extractall(path)
    zip_file.close()

project_id='5d385b6f1693055a45f6e876'
client, login_data = init_client()
download_project(client, login_data , project_id, path='test')



