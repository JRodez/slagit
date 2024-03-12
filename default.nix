{ pkgs ? import <nixos-unstable> { }
, lib ? pkgs.lib
, python3Packages ? pkgs.python3Packages
, fetchPypi ? pkgs.fetchPypi
, nixosTests ? pkgs.nixosTests
, fetchFromGitHub ? pkgs.fetchFromGitHub
}:
let
  socketio-client5-7-2 = python3Packages.socketio-client.overridePythonAttrs (oldAttrs: {
    version = "0.5.7.2";
    src = fetchPypi {
      version = "0.5.7.2";
      pname = "socketIO-client";
      sha256 = "sha256-i6BLzI2HVt1RGsQCFfsVWqEbYPAW/P/J5E+rNp4h5XU=";
    };
  });

  ezpylog2-2-0 = import
    (builtins.fetchTarball {
      url = "https://github.com/JRodez/ezpylog/archive/master.tar.gz";
    })
    { pkgs = pkgs; };

in


python3Packages.buildPythonPackage rec {
  # format = "pyproject";
  pname = "slagit";
  version = "2.0.2";
  doCheck = false;

  # src = pkgs.fetchPypi {
  #   inherit pname version;
  #   sha256 = "sha256-bkjMu6H4+GjNSmCSOjq+JePNIZ2wXOTMX5QnYLGxLKE=";
  # };

  src = ./.;


  nativeBuildInputs = [
    python3Packages.build
    python3Packages.setuptools
  ];
  propagatedBuildInputs = with python3Packages; [
    # socketIO-client==0.5.7.4
    # websocket-client==0.59.0
    # click~=8.0
    # GitPython~=2.1.13
    # filetype~=1.0.5
    # keyring>=17.1.1,<23.9.0
    # lxml>=4.3.3
    # python-dateutil>= 2.7.3
    # appdirs >= 1.4.3
    # requests >= 2.27.0
    pkgs.git
    socketio-client5-7-2
    websocket-client
    click
    gitpython
    filetype
    keyring
    lxml
    python-dateutil
    appdirs
    requests
    ezpylog2-2-0
  ];

  meta = with lib; {
    homepage = "https://github.com/jrodez/slagit";
    license = licenses.gpl3;
    description = "A command-line tool to synchronize Overleaf projects with local files over git";
    maintainers = with maintainers; [ jrodez ];
  };
}
