import json
import logging
import os
import pathlib
import shlex
import subprocess
from json.decoder import JSONDecodeError
from os import environ as env
from typing import List

from ._py_op_deprecation import deprecated
from .op_cli_version import OPCLIVersion
from .op_items._op_items_base import OPAbstractItem
from .py_op_exceptions import (
    OPCmdFailedException,
    OPConfigNotFoundException,
    OPInvalidItemException,
    OPNotFoundException,
    OPNotSignedInException,
    OPSigninException
)

"""
Module to hold stuff that interacts directly with 'op' or its config

TODO: Move other code that closely touches 'op' here
"""


class OPCLIConfig(dict):
    OP_CONFIG_PATHS = [
        pathlib.Path(".config", "op", "config"),
        pathlib.Path(".op", "config")
    ]

    def __init__(self, configpath=None):
        super().__init__()
        if configpath is None:
            configpath = self._get_config_path()
        self.configpath = configpath
        if configpath is None:
            raise OPConfigNotFoundException("No op configuration found")

        try:
            config_json = open(configpath, "r").read()
        except FileNotFoundError as e:
            raise OPConfigNotFoundException(
                "op config not found at path: {}".format(configpath)) from e
        except PermissionError as e:
            raise OPConfigNotFoundException(
                "Permission denied accessing op config at path: {}".format(configpath)) from e

        try:
            config = json.loads(config_json)
            self.update(config)
        except JSONDecodeError as e:
            raise OPConfigNotFoundException(
                "Unable to json decode config at path: {}".format(configpath)) from e

    def _get_config_path(self):
        configpath = None
        config_home = None
        try:
            config_home = os.environ['XDG_CONFIG_HOME']
        except KeyError:
            config_home = pathlib.Path.home()

        for subpath in self.OP_CONFIG_PATHS:
            _configpath = pathlib.Path(config_home, subpath)
            if os.path.exists(_configpath):
                configpath = _configpath
                break

        return configpath

    def get_config(self, shorthand=None):
        if shorthand is None:
            shorthand = self.get("latest_signin")
        if shorthand is None:
            raise OPConfigNotFoundException(
                "No shorthand provided, no sign-ins found.")
        accounts: List = self["accounts"]
        config = None
        for acct in accounts:
            if acct["shorthand"] == shorthand:
                config = acct

        if config is None:
            raise OPConfigNotFoundException(
                f"No config found for shorthand {shorthand}")

        return config


class _OPCLIExecute:
    NOT_SIGNED_IN_TEXT = "not currently signed in"

    logging.basicConfig(format="%(message)s", level=logging.DEBUG)
    logger = logging.getLogger()
    """
    Class for logging into and querying a 1Password account via the 'op' cli command.
    """
    OP_PATH = 'op'  # let subprocess find 'op' in the system path

    def __init__(self,
                 account_shorthand=None,
                 signin_address=None,
                 email_address=None,
                 secret_key=None,
                 password=None,
                 logger=None,
                 op_path='op',
                 use_existing_session=False,
                 password_prompt=True):
        """
        Create an OP object. The 1Password sign-in happens during object instantiation.
        If 'password' is not provided, the 'op' command will prompt on the console for a password.

        If all components of a 1Password account are provided, an initial sign-in is performed,
        otherwise, a normal sign-in is performed. See `op --help` for further explanation.

        Arguments:
            - 'account_shorthand': The shorthand name for the account on this device.
                                   You may choose this during initial signin, otherwise
                                   1Password converts it from your account address.
                                   See 'op signin --help' for more information.
            - 'signin_address': Fully qualified address of the 1Password account.
                                E.g., 'my-account.1password.com'
            - 'email_address': Email of the address for the user of the account
            - 'secret_key': Secret key for the account
            - 'password': The user's master password
            - 'logger': A logging object. If not provided a basic logger is created and used.
            - 'op_path': optional path to the `op` command, if it's not at the default location

        Raises:
            - OPSigninException if 1Password sign-in fails for any reason.
            - OPNotFoundException if the 1Password command can't be found.
        """
        if logger:
            self.logger = logger
        self._cli_version: OPCLIVersion = self._get_cli_version(op_path)
        if account_shorthand is None:
            config = OPCLIConfig()
            try:
                account_shorthand = config['latest_signin']
                self.logger.debug(
                    "Using account shorthand found in op config: {}".format(account_shorthand))
            except KeyError:
                account_shorthand = None

        if account_shorthand is None:
            raise OPNotSignedInException(
                "Account shorthand not provided and not found in 'op' config")

        sess_var_name = 'OP_SESSION_{}'.format(account_shorthand)

        self._token = None

        self.account_shorthand = account_shorthand
        self.op_path = op_path

        initial_signin_args = [account_shorthand,
                               signin_address,
                               email_address,
                               secret_key,
                               password]
        initial_signin = (None not in initial_signin_args)

        if use_existing_session:
            self._token = self._verify_signin(sess_var_name)

        if not self._token:
            if not password and not password_prompt:
                raise OPNotSignedInException(
                    "No existing session and no password provided.")
            if initial_signin:
                self._token = self._do_initial_signin(*initial_signin_args)
                # export OP_SESSION_<signin_address>
            else:
                self._token = self._do_normal_signin(
                    account_shorthand, password)

        # TODO: return already-decoded token from sign-in
        self._sess_var = sess_var_name
        env[sess_var_name] = self.token

    @property
    def token(self) -> str:
        return self._token

    @property
    def session_var(self) -> str:
        return self._sess_var

    def _get_cli_version(self, op_path):
        argv = _OPArgv.cli_version_argv(op_path)
        output = self._run(argv, capture_stdout=True, decode="utf-8")
        output = output.rstrip()
        cli_version = OPCLIVersion(output)
        return cli_version

    def _verify_signin(self, sess_var_name):
        # Need to get existing token if we're already signed in
        token = env.get(sess_var_name)

        if token:
            # if there's no token, no need to sign in
            argv = _OPArgv.get_verify_signin_argv(self.op_path)
            try:
                self._run(argv, capture_stdout=True)
            except OPCmdFailedException as opfe:
                # scrape error message about not being signed in
                # invalidate token if we're not signed in
                if self.NOT_SIGNED_IN_TEXT in opfe.err_output:
                    token = None
                else:
                    # there was a different error so raise the exception
                    raise opfe

        return token

    def _do_normal_signin(self, account_shorthand, password):
        self.logger.info("Doing normal (non-initial) 1Password sign-in")
        signin_argv = _OPArgv.normal_signin_argv(
            self.op_path, account_shorthand=account_shorthand)

        token = self._run_signin(signin_argv, password=password).rstrip()
        return token.decode()

    @deprecated("Initial sign-in soon to be deprecated due to incompatibility with multi-factor authentication")
    def _do_initial_signin(self, account_shorthand, signin_address, email_address, secret_key, password):
        self.logger.info(
            "Performing initial 1Password sign-in to {} as {}".format(signin_address, email_address))
        signin_argv = [self.op_path, "signin", signin_address,
                       email_address, secret_key, "--raw"]
        if account_shorthand:
            signin_argv.extend(["--shorthand", account_shorthand])

        token = self._run_signin(signin_argv, password=password).rstrip()

        return token.decode()

    def _run_signin(self, argv, password=None):
        try:
            output = self._run(argv, capture_stdout=True,
                               input_string=password)
        except OPCmdFailedException as opfe:
            raise OPSigninException.from_opexception(opfe) from opfe

        return output

    @classmethod
    def _run_raw(cls, argv, input_string=None, capture_stdout=False, ignore_error=False):
        stdout = subprocess.PIPE if capture_stdout else None
        if input_string:
            if isinstance(input_string, str):
                input_string = input_string.encode("utf-8")

        _ran = subprocess.run(
            argv, input=input_string, stderr=subprocess.PIPE, stdout=stdout, env=env)

        stdout = _ran.stdout
        stderr = _ran.stderr
        returncode = _ran.returncode

        if not ignore_error:
            try:
                _ran.check_returncode()
            except subprocess.CalledProcessError as err:
                stderr_output = stderr.decode("utf-8").rstrip()
                raise OPCmdFailedException(stderr_output, returncode) from err

        return (stdout, stderr, returncode)

    @classmethod
    def _run(cls, argv, capture_stdout=False, input_string=None, decode=None):
        output = None
        try:
            output, _, _ = cls._run_raw(
                argv, input_string=input_string, capture_stdout=capture_stdout)
            if decode:
                output = output.decode(decode)
        except FileNotFoundError as err:
            cls.logger.error(
                "1Password 'op' command not found at: {}".format(argv[0]))
            cls.logger.error(
                "See https://support.1password.com/command-line-getting-started/ for more information,")
            cls.logger.error(
                "or install from Homebrew with: 'brew install 1password-cli")
            raise OPNotFoundException(argv[0], err.errno) from err

        return output


class _OPArgv(list):
    """
    This is essentially an 'argv' list with some additional methods, such as class methods
    for generating proper argument lists for specific 1Password operations.

    The primary purpose of this class is to facilitate the 'mock-op' project's automated response generation,
    as it allows the preciese set of command line arguments to be captured for later playback.
    """

    def __init__(self, op_exe: str, command: str, args: List, subcommand: str = None, global_args=[]):
        # TODO: Refactor this
        # constructor is getting too many specialized kwargs tied to
        # specific commands/subcommands
        # maybe instead of an "args" array plus a bunch of named kwargs,
        # send in a dict that gets passed through tree of argv building logic?
        argv = [op_exe]
        for arg in global_args:
            argv.append(arg)
        if command:
            argv.append(command)
        self.command = command
        self.subcommand = None

        # whatever flags the command or subcommand take, plust global flags
        self.args_to_command = args

        if subcommand:
            self.subcommand = subcommand
            argv.extend([subcommand])
        argv.extend(args)
        super().__init__(argv)

    def query_args(self):
        args = list(self[1:])
        return args

    def cmd_str(self):
        """
        return a shell-escaped command string from this argv
        """
        cmd_str = shlex.join(self)
        return cmd_str

    @classmethod
    def get_generic_argv(cls, op_exe, get_subcommand, obj_identifier, sub_cmd_args):
        args = [obj_identifier]
        if sub_cmd_args:
            args.extend(sub_cmd_args)
        argv = cls(op_exe, "get", args, subcommand=get_subcommand)
        return argv

    @classmethod
    def get_item_argv(cls, op_exe, item_name_or_uuid, vault=None, fields=None):
        sub_cmd_args = []
        if vault:
            sub_cmd_args.extend(["--vault", vault])

        if fields:
            sub_cmd_args.extend(["--fields", fields])
        argv = cls.get_generic_argv(
            op_exe, "item", item_name_or_uuid, sub_cmd_args)
        return argv

    @classmethod
    def get_totp_argv(cls, op_exe, item_name_or_uuid, vault=None):
        sub_cmd_args = []
        if vault:
            sub_cmd_args.extend(["--vault", vault])

        argv = cls.get_generic_argv(
            op_exe, "totp", item_name_or_uuid, sub_cmd_args)
        return argv

    @classmethod
    def get_document_argv(cls, op_exe, document_name_or_uuid, vault=None):
        sub_cmd_args = []
        if vault:
            sub_cmd_args.extend(["--vault", vault])
        argv = cls.get_generic_argv(
            op_exe, "document", document_name_or_uuid, sub_cmd_args)
        return argv

    @classmethod
    def normal_signin_argv(cls, op_exe, account_shorthand=None):
        global_args = []
        if account_shorthand:
            global_args = ["--account", account_shorthand]
        argv = [account_shorthand, "--raw"]
        return cls(op_exe, "signin", argv, global_args=global_args)

    @classmethod
    def create_item_argv(cls, op_exe, item: OPAbstractItem, item_name: str, vault: str = None, encoding="utf-8"):
        if not item.is_from_template:
            raise OPInvalidItemException(
                f"Attempting to create item using object not from a template: {item_name}")
        template_filename = item.details_secure_tempfile(
            encoding=encoding)

        category = item.category

        argv = [category, "--title", item_name,
                "--template", template_filename]

        # unfortunately the 'op' command can only set one URL
        # so we need to get only the first one
        url = item.first_url()
        url_value = None
        if url:
            url_value = url.url
        if url_value:
            argv.extend(["--url", url_value])

        if vault:
            argv.extend(["--vault", vault])

        return cls(op_exe, "create", argv, subcommand="item")

    @classmethod
    def get_verify_signin_argv(cls, op_exe):
        argv = ["templates"]
        argv_obj = cls(op_exe, "list", argv)
        return argv_obj

    @classmethod
    def cli_version_argv(cls, op_exe):
        args = []
        global_args = ["--version"]
        argv_obj = cls(op_exe, None, args, global_args=global_args)
        return argv_obj

    @classmethod
    def signout_argv(cls, op_exe, account_shorthand: str, session: str, forget=False):
        global_args = ["--account", account_shorthand, "--session", session]
        signout_args = []
        if forget:
            signout_args.append("--forget")
        argv = cls(op_exe, "signout", signout_args, global_args=global_args)
        return argv

    @classmethod
    def forget_argv(cls, op_exe, account_shorthand):
        forget_args = [account_shorthand]
        argv = cls(op_exe, "forget", forget_args)
        return argv

    @classmethod
    def list_generic_argv(cls, op_exe, list_subcommand, sub_command_args):
        argv = cls(op_exe, "list", sub_command_args,
                   subcommand=list_subcommand)
        return argv

    @classmethod
    def list_items_argv(cls, op_exe, categories=[], include_archive=False, tags=[], vault=None):
        list_items_args = []
        if categories:
            categories_arg = ",".join(categories)
            list_items_args.extend(["--categories", categories_arg])
        if include_archive:
            list_items_args.append("--include-archive")
        if tags:
            tags_args = ",".join(tags)
            list_items_args.extend(["--tags", tags_args])
        if vault:
            list_items_args.extend(["--vault", vault])

        argv = cls.list_generic_argv(op_exe, "items", list_items_args)
        return argv
