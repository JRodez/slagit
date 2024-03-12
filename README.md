*Slagit* is a library to interact with
sharelatex.irit.fr. It also includes a command line tools to sync your
remote project with Git. This allows you to work offline on your project
and later sync your local copy with the remote one.

It's a fork of [a Matthieu Simonin's project](https://gitlab.inria.fr/sed-rennes/sharelatex/python-sharelatex.git)

Todo : nix package

# Links

- [Source](https://github.com/JRodez/slagit)
- [Pre-forked documentation (replace slatex with slagit)](https://sed-rennes.gitlabpages.inria.fr/sharelatex/python-sharelatex)
- [Pypi page](https://pypi.org/project/slagit/)



**The code is currently experimental and under development. Use it with
caution.**

# Installation

## From pypi :
``` bash
  pip install slagit
```

## From source :
``` bash
  git clone https://github.com/JRodez/slagit.git
  cd slagit
  pip install slagit

```

# Persistent sessions

Sessions are persistent and store in the application directory (exact
might differ on the OS used). Is uses
[appdirs](https://github.com/ActiveState/appdirs) internally.

# Note on passwords management

Passwords are stored in your keyring service (Keychain, Kwallet \...)
thanks to the [keyring](https://pypi.org/project/keyring/) library.
Please refer to the dedicated documentation for more information.

# Quick examples

## Display the possible actions

`slagit` is a subcommand of git that calls the `git-slagit`
programm shipped by this project.

``` bash
$) git slagit

Usage: git-slagit [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  clone    Get (clone) the files from sharelatex projet URL and crate a...
  compile  Compile the remote version of a project
  new      Upload the current directory as a new sharelatex project
  pull     Pull the files from sharelatex.
  push     Push the committed changes back to sharelatex
```

For instance you can get the help on a specific sub-command with the
following:

``` bash
git slagit clone --help
```

## Get an existing project on slagit

``` bash
mkdir test
cd test
# download all files of a remote project
git slagit clone <project_URL> <local_path_to_project>
```

## Editing and pushing back to slagit

``` bash
# edit your files
# commit, commit, commit ...
#
# Push back your change to sharelatex
git slagit push
```

Concurrent updates may occur between your local files (because you
changed them) and the remote ones (because you collaborators changed
them). So before pushing, we try to make sure the merge between the
remote copy and the local ones is ok. You\'ll have to resolve the
conflict manually (as usual with Git) and attempt a new push.

## Pull changes from sharelatex to local (like a git pull)

``` bash
# Pull changes from sharelatex
git slagit pull
```

## Create a remote project from a local git

``` bash
git slagit new [OPTIONS] PROJECTNAME BASE_URL
```
