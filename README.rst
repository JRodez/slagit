Pull/Push sharelatex project from/to GIT

Installation
------------


.. code:: bash

    # in the future ?
    pip install sharelatex


Configuration
-------------

.. code:: bash

    echo '
    username: MYLOGIN
    password: MYPASSWORD
    ' > ~/.sharelatex.yaml

    chmod 600 ~/.sharelatex.yaml

Example
-------

.. code:: bash

    mkdir test
    cd test
    # download all files of a remote project
    git slatex init <project_id>
    # edit your files
    git slatex push
