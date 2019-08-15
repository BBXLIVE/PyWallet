import os
import shutil
import unittest
from tempfile import mkdtemp
from unittest import mock

from eth_utils import to_checksum_address
from pywalib import (InsufficientFundsException, NoTransactionFoundException,
                     PyWalib, UnknownEtherscanException)

ADDRESS = "0xab5801a7d398351b8be11c439e05c5b3259aec9b"
VOID_ADDRESS = "0x0000000000000000000000000000000000000000"
PASSWORD = "password"


def patch_requests_get():
    return mock.patch('pywalib.requests.get')


class PywalibTestCase(unittest.TestCase):
    """
    Simple test cases, verifying pywalib works as expected.
    """

    def setUp(self):
        self.keystore_dir = mkdtemp()
        self.pywalib = PyWalib(self.keystore_dir)

    def tearDown(self):
        shutil.rmtree(self.keystore_dir, ignore_errors=True)

    def helper_new_account(self, password=PASSWORD, security_ratio=1):
        """
        Helper method for fast account creation.
        """
        account = self.pywalib.new_account(password, security_ratio)
        return account

    def test_new_account(self):
        """
        Simple account creation test case.
        1) verifies the current account list is empty
        2) creates a new account and verify we can retrieve it
        3) tries to unlock the account
        """
        pywalib = self.pywalib
        # 1) verifies the current account list is empty
        account_list = pywalib.get_account_list()
        self.assertEqual(len(account_list), 0)
        # 2) creates a new account and verify we can retrieve it
        password = PASSWORD
        # weak account, but fast creation
        security_ratio = 1
        account = pywalib.new_account(password, security_ratio)
        account_list = pywalib.get_account_list()
        self.assertEqual(len(account_list), 1)
        self.assertEqual(account, pywalib.get_main_account())
        # 3) tries to unlock the account
        # it's unlocked by default after creation
        self.assertFalse(account.locked)
        # let's lock it and unlock it back
        account.lock()
        self.assertTrue(account.locked)
        account.unlock(password)
        self.assertFalse(account.locked)

    def helper_test_new_account_security_ratio_ok(self, security_ratio):
        """
        Helper method to unit test `new_account()` security_ratio parameter on
        happy scenarios.
        """
        pywalib = self.pywalib
        password = PASSWORD
        with mock.patch.object(
                pywalib.account_utils, 'new_account') as m_new_account:
            self.assertIsNotNone(pywalib.new_account(password, security_ratio))
        self.assertEqual(
            m_new_account.call_args_list,
            [mock.call(iterations=mock.ANY, password='password')]
        )

    def helper_test_new_account_security_ratio_error(self, security_ratio):
        """
        Helper method to unit test `new_account()` security_ratio parameter on
        rainy scenarios.
        """
        password = PASSWORD
        with self.assertRaises(ValueError) as ex_info:
            self.pywalib.new_account(password, security_ratio)
        self.assertEqual(
            ex_info.exception.args[0],
            'security_ratio must be within 1 and 100')

    def test_new_account_security_ratio(self):
        """
        Checks the security_ratio parameter behave as expected.
        Possible value are:
            - security_ratio == None
            - security_ratio >= 1
            - security_ratio <= 100
        """
        security_ratio = None
        self.helper_test_new_account_security_ratio_ok(security_ratio)
        security_ratio = 1
        self.helper_test_new_account_security_ratio_ok(security_ratio)
        security_ratio = 100
        self.helper_test_new_account_security_ratio_ok(security_ratio)
        # anything else would fail
        security_ratio = 0
        self.helper_test_new_account_security_ratio_error(security_ratio)
        security_ratio = 101
        self.helper_test_new_account_security_ratio_error(security_ratio)

    def test_update_account_password(self):
        """
        Verifies updating account password works.
        """
        pywalib = self.pywalib
        current_password = "password"
        # weak account, but fast creation
        security_ratio = 1
        account = pywalib.new_account(current_password, security_ratio)
        # first try when the account is already unlocked
        self.assertFalse(account.locked)
        new_password = "new_password"
        # on unlocked account the current_password is optional
        pywalib.update_account_password(
            account, new_password, current_password=None)
        # verify it worked
        account.lock()
        account.unlock(new_password)
        self.assertFalse(account.locked)
        # now try when the account is first locked
        account.lock()
        current_password = "wrong password"
        with self.assertRaises(ValueError):
            pywalib.update_account_password(
                account, new_password, current_password)
        current_password = new_password
        pywalib.update_account_password(
            account, new_password, current_password)
        self.assertFalse(account.locked)

    def test_deleted_account_dir(self):
        """
        The deleted_account_dir() helper method should be working
        with and without trailing slash.
        """
        expected_deleted_keystore_dir = '/tmp/keystore-deleted'
        keystore_dirs = [
            # without trailing slash
            '/tmp/keystore',
            # with one trailing slash
            '/tmp/keystore/',
            # with two trailing slashes
            '/tmp/keystore//',
        ]
        for keystore_dir in keystore_dirs:
            self.assertEqual(
                PyWalib.deleted_account_dir(keystore_dir),
                expected_deleted_keystore_dir)

    def test_delete_account(self):
        """
        Creates a new account and delete it.
        Then verify we can load the account from the backup/trash location.
        """
        pywalib = self.pywalib
        account = self.helper_new_account()
        address = account.address
        self.assertEqual(len(pywalib.get_account_list()), 1)
        # deletes the account and verifies it's not loaded anymore
        pywalib.delete_account(account)
        self.assertEqual(len(pywalib.get_account_list()), 0)
        # even recreating the PyWalib object
        pywalib = PyWalib(self.keystore_dir)
        self.assertEqual(len(pywalib.get_account_list()), 0)
        # tries to reload it from the backup/trash location
        deleted_keystore_dir = PyWalib.deleted_account_dir(self.keystore_dir)
        pywalib = PyWalib(deleted_keystore_dir)
        self.assertEqual(len(pywalib.get_account_list()), 1)
        self.assertEqual(pywalib.get_account_list()[0].address, address)

    def test_delete_account_already_exists(self):
        """
        If the destination (backup/trash) directory where the account is moved
        already exists, it should be handled gracefully.
        This could happens if the account gets deleted, then reimported and
        deleted again, refs:
        https://github.com/AndreMiras/PyWallet/issues/88
        """
        pywalib = self.pywalib
        account = self.helper_new_account()
        # creates a file in the backup/trash folder that would conflict
        # with the deleted account
        deleted_keystore_dir = PyWalib.deleted_account_dir(self.keystore_dir)
        os.makedirs(deleted_keystore_dir)
        account_filename = os.path.basename(account.path)
        deleted_account_path = os.path.join(
            deleted_keystore_dir, account_filename)
        # create that file
        open(deleted_account_path, 'a').close()
        # then deletes the account and verifies it worked
        self.assertEqual(len(pywalib.get_account_list()), 1)
        pywalib.delete_account(account)
        self.assertEqual(len(pywalib.get_account_list()), 0)

    def test_handle_etherscan_error(self):
        """
        Checks handle_etherscan_error() error handling.
        """
        # no transaction found
        response_json = {
            'message': 'No transactions found', 'result': [], 'status': '0'
        }
        with self.assertRaises(NoTransactionFoundException):
            PyWalib.handle_etherscan_error(response_json)
        # unknown error
        response_json = {
            'message': 'Unknown error', 'result': [], 'status': '0'
        }
        with self.assertRaises(UnknownEtherscanException) as e:
            PyWalib.handle_etherscan_error(response_json)
        self.assertEqual(e.exception.args[0], response_json)
        # no error
        response_json = {
            'message': 'OK', 'result': [], 'status': '1'
        }
        self.assertEqual(
            PyWalib.handle_etherscan_error(response_json),
            None)

    def test_get_balance(self):
        """
        Checks get_balance() returns a float.
        """
        pywalib = self.pywalib
        address = ADDRESS
        with patch_requests_get() as m_get:
            m_get.return_value.json.return_value = {
                'status': '1',
                'message': 'OK',
                'result': '350003576885437676061958',
            }
            balance_eth = pywalib.get_balance(address)
        self.assertEqual(balance_eth, 350003.577)

    def test_get_balance_web3(self):
        """
        Checks get_balance() returns a float.
        """
        pywalib = self.pywalib
        address = ADDRESS
        with mock.patch('web3.eth.Eth.getBalance') as m_getBalance:
            m_getBalance.return_value = 350003576885437676061958
            balance_eth = pywalib.get_balance_web3(address)
        checksum_address = to_checksum_address(address)
        self.assertEqual(
            m_getBalance.call_args_list,
            [mock.call(checksum_address)]
        )
        self.assertTrue(type(balance_eth), float)
        self.assertEqual(balance_eth, 350003.577)

    def helper_test_get_history(self, transactions):
        """
        Helper method to test history related methods.
        """
        self.assertEqual(type(transactions), list)
        self.assertTrue(len(transactions) > 1)
        # ordered by timeStamp
        self.assertTrue(
            transactions[0]['timeStamp'] < transactions[1]['timeStamp'])
        # and a bunch of other things
        self.assertEqual(
            set(transactions[0].keys()),
            set([
                'nonce', 'contractAddress', 'cumulativeGasUsed', 'hash',
                'blockHash', 'extra_dict', 'timeStamp', 'gas', 'value',
                'blockNumber', 'to', 'confirmations', 'input', 'from',
                'transactionIndex', 'isError', 'gasPrice', 'gasUsed',
                'txreceipt_status',
            ]))

    def test_get_transaction_history(self):
        """
        Checks get_transaction_history() works as expected.
        """
        address = ADDRESS
        # not dumping the full payload for readability
        transactions = [
            {'blockHash': (
                '0x0e37d0025471662915d7a15ade9a13e'
                '75cbbcc239bdbc4ea46a01d9b268a7e60'
             ),
             'blockNumber': '207947',
             'confirmations': '8142357',
             'contractAddress': '',
             'cumulativeGasUsed': '21408',
             'from': '0x5ed8cee6b63b1c6afce3ad7c92f4fd7e1b8fad9f',
             'gas': '90000',
             'gasPrice': '50000000000',
             'gasUsed': '21408',
             'hash': (
                '0xf7dbf98bcebd7b803917e00e7e329284'
                '3a4b7bf66016638811cea4705a32d73e'
             ),
             'input': '0x123123123123',
             'isError': '0',
             'nonce': '23',
             'timeStamp': '1441800674',
             'to': '0xab5801a7d398351b8be11c439e05c5b3259aec9b',
             'transactionIndex': '0',
             'txreceipt_status': '',
             'value': '0'
             },
            {'blockHash': (
                '0x84fcddbf660faa265e55e877490cbb8'
                '1cbb69e8fe14dbc8f15aaef586e9cd762'
             ),
             'from': '0x5ed8cee6b63b1c6afce3ad7c92f4fd7e1b8fad9f',
             'timeStamp': '1441801055',
             'to': '0xab5801a7d398351b8be11c439e05c5b3259aec9b',
             'value': '200000000000000000'
             },
            {'blockHash': (
                '0xc8bc4bccc0359db2e984221cffde819'
                '0fb126ca911c95f041df7e7358a22e361'
             ),
             'from': '0xab5801a7d398351b8be11c439e05c5b3259aec9b',
             'timeStamp': '1441801303',
             'to': '0x3535353535353535353535353535353535353535',
             'value': '100'
             },
        ]
        with patch_requests_get() as m_get:
            m_get.return_value.json.return_value = {
                'status': '1',
                'message': 'OK',
                'result': transactions,
            }
            transactions = PyWalib.get_transaction_history(address)
        self.helper_test_get_history(transactions)
        # value is stored in Wei
        self.assertEqual(transactions[1]['value'], '200000000000000000')
        # but converted to Ether is also accessible
        self.assertEqual(transactions[1]['extra_dict']['value_eth'], 0.2)
        # history contains all send or received transactions
        self.assertEqual(transactions[1]['extra_dict']['sent'], False)
        self.assertEqual(transactions[1]['extra_dict']['received'], True)
        self.assertEqual(transactions[2]['extra_dict']['sent'], True)
        self.assertEqual(transactions[2]['extra_dict']['received'], False)

    def test_get_out_transaction_history(self):
        """
        Checks get_out_transaction_history() works as expected.
        """
        address = ADDRESS
        transactions = PyWalib.get_out_transaction_history(address)
        self.helper_test_get_history(transactions)
        for i in range(len(transactions)):
            transaction = transactions[i]
            extra_dict = transaction['extra_dict']
            # this is only sent transactions
            self.assertEqual(extra_dict['sent'], True)
            self.assertEqual(extra_dict['received'], False)
            # nonce should be incremented each time
            self.assertEqual(transaction['nonce'], str(i))

    def test_get_nonce(self):
        """
        Checks get_nonce() returns the next nonce, i.e. transaction count.
        """
        address = ADDRESS
        nonce = PyWalib.get_nonce(address)
        transactions = PyWalib.get_out_transaction_history(address)
        last_transaction = transactions[-1]
        last_nonce = int(last_transaction['nonce'])
        self.assertEqual(nonce, last_nonce + 1)

    def test_get_nonce_no_out_transaction(self):
        """
        Makes sure get_nonce() doesn't crash on no out transaction,
        but just returns 0.
        """
        # the VOID_ADDRESS has a lot of in transactions,
        # but no out ones, so the nonce should be 0
        address = VOID_ADDRESS
        # truncated for readability
        transactions = [
            {'blockHash': (
                '0x7e5a9336dd82efff0bfe8c25ccb0e8c'
                'f44b4c6f781b25b3fc3578f004f60b872'
             ),
             'from': '0x22f2dcff5ad78c3eb6850b5cb951127b659522e6',
             'timeStamp': '1438922865',
             'to': '0x0000000000000000000000000000000000000000',
             'value': '0'}
        ]
        with patch_requests_get() as m_get:
            m_get.return_value.json.return_value = {
                'status': '1',
                'message': 'OK',
                'result': transactions,
            }
            nonce = PyWalib.get_nonce(address)
        self.assertEqual(nonce, 0)

    def test_get_nonce_no_transaction(self):
        """
        Makes sure get_nonce() doesn't crash on no transaction,
        but just returns 0.
        """
        # the newly created address has no in or out transaction history
        account = self.helper_new_account()
        address = account.address
        nonce = PyWalib.get_nonce(address)
        self.assertEqual(nonce, 0)

    def test_handle_web3_exception(self):
        """
        Checks handle_web3_exception() error handling.
        """
        # insufficient funds
        exception = ValueError({
            'code': -32000,
            'message': 'insufficient funds for gas * price + value'
        })
        with self.assertRaises(InsufficientFundsException) as e:
            PyWalib.handle_web3_exception(exception)
        self.assertEqual(e.exception.args[0], exception.args[0])
        # unknown error code
        exception = ValueError({
            'code': 0,
            'message': 'Unknown error'
        })
        with self.assertRaises(UnknownEtherscanException) as e:
            PyWalib.handle_web3_exception(exception)
        self.assertEqual(e.exception.args[0], exception.args[0])
        # no code
        exception = ValueError({
            'message': 'Unknown error'
        })
        with self.assertRaises(UnknownEtherscanException) as e:
            PyWalib.handle_web3_exception(exception)
        self.assertEqual(e.exception.args[0], exception.args[0])

    def test_transact(self):
        """
        Basic transact() test, makes sure web3 sendRawTransaction gets called.
        """
        pywalib = self.pywalib
        account = self.helper_new_account()
        to = ADDRESS
        sender = account.address
        value_wei = 100
        with mock.patch('web3.eth.Eth.sendRawTransaction') \
                as m_sendRawTransaction:
            pywalib.transact(to=to, value=value_wei, sender=sender)
        self.assertTrue(m_sendRawTransaction.called)

    def test_transact_no_sender(self):
        """
        The sender parameter should default to the main account.
        Makes sure the transaction is being signed by the available account.
        """
        pywalib = self.pywalib
        account = self.helper_new_account()
        to = ADDRESS
        value_wei = 100
        with mock.patch('web3.eth.Eth.sendRawTransaction') \
                as m_sendRawTransaction, \
                mock.patch('web3.eth.Eth.account.signTransaction') \
                as m_signTransaction:
            pywalib.transact(to=to, value=value_wei)
        self.assertTrue(m_sendRawTransaction.called)
        m_signTransaction.call_args_list
        transaction = {
            'chainId': 1,
            'gas': 25000,
            'gasPrice': 4000000000,
            'nonce': 0,
            'value': value_wei,
        }
        expected_call = mock.call(transaction, account.privkey)
        self.assertEqual(m_signTransaction.call_args_list, [expected_call])

    def test_transact_no_funds(self):
        """
        Tries to send a transaction from an address with no funds.
        """
        pywalib = self.pywalib
        account = self.helper_new_account()
        to = ADDRESS
        sender = account.address
        value_wei = 100
        with self.assertRaises(InsufficientFundsException):
            pywalib.transact(to=to, value=value_wei, sender=sender)

    def test_get_default_keystore_path(self):
        """
        Checks we the default keystore directory exists or create it.
        Verify the path is correct and that we have read/write access to it.
        """
        keystore_dir = PyWalib.get_default_keystore_path()
        if not os.path.exists(keystore_dir):
            os.makedirs(keystore_dir)
        # checks path correctness
        self.assertTrue(keystore_dir.endswith(".config/pyethapp/keystore/"))
        # checks read/write access
        self.assertEqual(os.access(keystore_dir, os.R_OK), True)
        self.assertEqual(os.access(keystore_dir, os.W_OK), True)
