import time
import unittest
import pprint
import logging
import os

from iconsdk.builder.call_builder import CallBuilder
from iconsdk.libs.in_memory_zip import gen_deploy_data_content
from iconsdk.builder.transaction_builder import DeployTransactionBuilder, CallTransactionBuilder, Transaction, \
    TransactionBuilder
from iconsdk.exception import JSONRPCException
from iconsdk.providers.http_provider import HTTPProvider
from iconsdk.signed_transaction import SignedTransaction
from iconsdk.wallet.wallet import KeyWallet
from iconsdk.icon_service import IconService


class MultiSigBridgeTest(unittest.TestCase):
    _owners = []

    SCORE_INSTALL_ADDRESS = f"cx{'0' * 40}"
    GOV_SCORE_ADDRESS = "cx0000000000000000000000000000000000000001"

    LOCAL_NETWORK_TEST = True

    LOCAL_TEST_HTTP_ENDPOINT_URI_V3 = "http://127.0.0.1:9000/api/v3"
    YEUOIDO_TEST_HTTP_ENDPOINT_URI_V3 = "https://bicon.net.solidwallet.io/api/v3"

    pp = pprint.PrettyPrinter(indent=4)

    # Gets executed before the whole Testsuite
    @classmethod
    def setUpClass(cls) -> None:
        logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)

        if MultiSigBridgeTest.LOCAL_NETWORK_TEST:
            cls._owners.append(KeyWallet.load("../../keystore_test1", "test1_Account"))
            cls._icon_service = IconService(HTTPProvider(cls.LOCAL_TEST_HTTP_ENDPOINT_URI_V3))
        else:
            cls._owners.append(KeyWallet.load("../bridge_testing_wallet", "I_WONT_GIVE_YOU_MY_PASSWORD"))
            cls._icon_service = IconService(HTTPProvider(cls.YEUOIDO_TEST_HTTP_ENDPOINT_URI_V3))

        for i in range(4):
            new_owner = KeyWallet.create()
            cls._owners.append(new_owner)

            multi_sig_bridge_test = MultiSigBridgeTest()
            tx = cls._buildTransaction(multi_sig_bridge_test, type="transfer", value=1150250000000000000,
                                       from_=cls._owners[0].get_address(), to_=new_owner.get_address())
            signed_transaction = SignedTransaction(tx, cls._owners[0])
            cls._icon_service.send_transaction(signed_transaction)

    # Gets executed before each Testcase
    def setUp(self) -> None:
        self._score_address = self._testDeploy(params={"_walletOwners": self._owners[0].get_address() + "," +
                                                self._owners[1].get_address(),"_required": "0x02"})["scoreAddress"]

    #################################################################################################################
    # TEST CASES
    #################################################################################################################

    def testUpdate(self):
        tx_result = self._testDeploy(deploy_address=self._score_address)
        self.assertEqual(self._score_address, tx_result['scoreAddress'], "Updating the SCORE failed!")

    def testBalance(self):
        for i in range(5):
            self.assertNotEqual(0, self._icon_service.get_balance(self._owners[i].get_address()),
                                "Owner[i] should have balance but does not!")

    def testAddOwner(self):
        # Submit Add Owner TX
        tx_result = self._addOwner(from_=self._owners[0], new_owner=self._owners[2].get_address())

        self.assertEqual(True, tx_result["status"], "Submitting addWalletOwner TX should succeed but does not!")
        self.assertNotIn(self._owners[2].get_address(), self._getWalletOwners(),
                         "Owner[2] is wallet owner before adding him!")

        # Confirm Add Owner TX
        tx_result = self._confirmLastTX(self._owners[1])
        self.assertEqual(True, tx_result["status"],
                         "Submitting confirmation of addWalletOwner TX should succeed but does not!")

        # Assert that added wallet is now owner
        self.assertIn(self._owners[2].get_address(), self._getWalletOwners(),
                      "Owner[2] is not wallet owner after adding him!")

    def testAddOwnerFail(self):
        tx_result = self._addOwner(from_=self._owners[0], new_owner="hx0123456789abcde")
        self.assertEqual(False, tx_result["status"],
                         "Submitting addWalletOwner TX with faulty address should fail but does not!")

        tx_result = self._addOwner(from_=self._owners[4], new_owner=self._owners[2].get_address())
        self.assertEqual(False, tx_result["status"],
                         "Submitting addWalletOwner TX with non-owner as submitter should fail but does not!")

        self._addOwner(from_=self._owners[0], new_owner=self._owners[0].get_address())
        tx_result = self._confirmLastTX(from_=self._owners[1])
        self.assertIn("ExecutionFailure(int)", tx_result["eventLogs"][1]["indexed"],
                      "Submitting addWalletOwner TX with already owner as new owner should fail but does not!")

        self.assertNotIn(self._owners[2].get_address(), self._getWalletOwners(),
                         "Owner[2] is wallet owner even though he was never added!")

    def testReplaceOwner(self):
        # Submit Replace Owner TX
        tx_result = self._replaceOwner(from_=self._owners[0], old_owner=self._owners[1].get_address(), new_owner=self._owners[2].get_address())

        self.assertEqual(True, tx_result["status"], "Submitting replaceWalletOwner TX should succeed but does not!")
        self.assertIn(self._owners[1].get_address(), self._getWalletOwners(),
                      "Owner[1] is not wallet owner but he should be!")
        self.assertNotIn(self._owners[2].get_address(), self._getWalletOwners(),
                         "Owner[2] is wallet owner before adding him as a replacement!")

        # Confirm Replace Owner TX
        tx_result = self._confirmLastTX(self._owners[1])
        self.assertEqual(True, tx_result["status"],
                         "Submitting confirmation of replaceWalletOwner TX should succeed but does not!")

        # Assert that owner1 got replaced with owner2
        self.assertNotIn(self._owners[1].get_address(), self._getWalletOwners(),
                         "Owner[1] is still owner although he was just replaced!")
        self.assertIn(self._owners[2].get_address(), self._getWalletOwners(),
                      "Owner[2] is not wallet owner after adding him!")

    def testReplaceOwnerFail(self):
        pass

    def testRemoveOwner(self):
        # Add an owner to remove one later
        self._addOwner(from_=self._owners[0], new_owner=self._owners[2].get_address())
        self._confirmLastTX(self._owners[1])

        # Submit Remove Owner TX
        tx_result = self._removeOwner(from_=self._owners[0], owner=self._owners[1].get_address())

        self.assertEqual(True, tx_result["status"], "Submitting removeWalletOwner TX should succeed but does not!")
        self.assertIn(self._owners[1].get_address(), self._getWalletOwners(),
                      "Owner[2] is not wallet owner before deleting him!")

        # Confirm Remove Owner TX
        tx_result = self._confirmLastTX(self._owners[2])
        self.assertEqual(True, tx_result["status"],
                         "Submitting confirmation of removeWalletOwner TX should succeed but does not!")

        # Assert that wallet owner got removed
        self.assertNotIn(self._owners[1].get_address(), self._getWalletOwners(),
                         "Owner[1] is still wallet owner after removing him!")

    def testRemoveOwnerFail(self):
        pass

    def testConfirmFail(self):
        tx = self._buildTransaction(type="write", from_=self._owners[0].get_address(), method="confirmTransaction",
                                    params={"_transactionId": 12345})
        signed_transaction = SignedTransaction(tx, self._owners[0])

        tx_hash = self._icon_service.send_transaction(signed_transaction)
        tx_result = self._getTXResult(tx_hash)

        self.assertEqual(False, tx_result["status"],
                         "Confirming a non existing TX should fail but does not!")

    #################################################################################################################
    # UTILS
    #################################################################################################################

    def _getTXResult(self, tx_hash) -> dict:
        logger = logging.getLogger('ICON-SDK-PYTHON')
        logger.disabled = True
        while True:
            try:
                res = self._icon_service.get_transaction_result(tx_hash)
                logger.disabled = False
                return res
            except JSONRPCException as e:
                if e.args[0]["message"] == "Pending transaction":
                    time.sleep(1)

    def _estimateSteps(self, margin) -> int:
        tx = self._buildTransaction(type="read", method="getStepCosts", to_=MultiSigBridgeTest.GOV_SCORE_ADDRESS, params={})
        result = self._icon_service.call(tx)
        return int(result["contractCall"], 16) + margin

    def _buildTransaction(self, type="write", **kwargs) -> Transaction:
        if type not in ("transfer", "write", "read"):
            raise ValueError("Wrong method value")

        from_ = KeyWallet.create() if "from_" not in kwargs else kwargs["from_"]
        to_ = self._score_address if "to_" not in kwargs else kwargs["to_"]
        margin_ = 15000000 if "margin" not in kwargs else kwargs["margin"]
        value_ = 0 if "value" not in kwargs else kwargs["value"]
        method_ = None if "method" not in kwargs else kwargs["method"]
        params_ = {} if "params" not in kwargs else kwargs["params"]

        if type == "write":
            steps_ = self._estimateSteps(margin_)
            tx = CallTransactionBuilder() \
                .from_(from_) \
                .to(to_) \
                .value(value_) \
                .nid(3) \
                .step_limit(steps_) \
                .nonce(100) \
                .method(method_) \
                .params(params_) \
                .build()
        elif type == "read":
            tx = CallBuilder() \
                .to(to_) \
                .method(method_) \
                .params(params_) \
                .build()
        elif type == "transfer":
            steps_ = self._estimateSteps(margin_)
            tx = TransactionBuilder()\
                .from_(from_)\
                .to(to_)\
                .value(value_) \
                .step_limit(steps_) \
                .nid(3) \
                .build()

        return tx

    def _testDeploy(self, params: dict = {}, deploy_address: str = SCORE_INSTALL_ADDRESS) -> dict:
        dir_path = os.path.abspath(os.path.dirname(__file__))
        score_project = os.path.abspath(os.path.join(dir_path, '../multisig_wallet'))
        score_content_bytes = gen_deploy_data_content(score_project)

        transaction = DeployTransactionBuilder() \
            .from_(self._owners[0].get_address()) \
            .to(deploy_address) \
            .nid(3) \
            .step_limit(10000000000) \
            .nonce(100) \
            .content_type("application/zip") \
            .content(score_content_bytes) \
            .params(params) \
            .build()

        # estimated_steps = self._estimateSteps(transaction)
        signed_transaction = SignedTransaction(transaction, self._owners[0])

        tx_hash = self._icon_service.send_transaction(signed_transaction)
        tx_result = self._getTXResult(tx_hash)

        MultiSigBridgeTest.pp.pprint(tx_result)

        self.assertEqual(True, tx_result["status"], "Deploying the SCORE failed!")
        self.assertTrue('scoreAddress' in tx_result, "scoreAddress should be in deployment TX but is not!")

        return tx_result

    def _confirmLastTX(self, from_: KeyWallet):
        tx_list = self._getTXList()
        tx_id = tx_list[len(tx_list) - 1]["_transactionId"]
        params = {"_transactionId": tx_id}

        tx = self._buildTransaction(type="write", from_=from_.get_address(), method="confirmTransaction",
                                    params=params)
        signed_transaction = SignedTransaction(tx, from_)

        tx_hash = self._icon_service.send_transaction(signed_transaction)
        tx_result = self._getTXResult(tx_hash)
        MultiSigBridgeTest.pp.pprint(tx_result)

        return tx_result

    def _addOwner(self, from_: KeyWallet, new_owner: str) -> dict:
        params = {"_destination": self._score_address,
                  "_method": "addWalletOwner",
                  "_params": "[{\"name\":\"_walletOwner\",\"type\":\"Address\",\"value\":\"" + new_owner + "\"}]",
                  "_description": "add new owner in wallet"}

        return self._writeTX(params=params, from_=from_)

    def _replaceOwner(self, from_: KeyWallet, old_owner: str, new_owner: str) -> dict:
        params = {"_destination": self._score_address,
                  "_method": "replaceWalletOwner",
                  "_params": "[{\"name\":\"_walletOwner\",\"type\":\"Address\",\"value\":\"" + old_owner + "\"},"
                             "{\"name\":\"_newWalletOwner\",\"type\":\"Address\",\"value\":\"" + new_owner + "\"}]",
                  "_description": "replace owner in wallet"}

        return self._writeTX(params=params, from_=from_)

    def _removeOwner(self, from_: KeyWallet, owner: str) -> dict:
        params = {"_destination": self._score_address,
                  "_method": "removeWalletOwner",
                  "_params": "[{\"name\":\"_walletOwner\",\"type\":\"Address\",\"value\":\"" + owner + "\"}]",
                  "_description": "remove owner from wallet"}

        return self._writeTX(params=params, from_=from_)

    def _writeTX(self, params: dict, from_: KeyWallet) -> dict:
        tx = self._buildTransaction(type="write", from_=from_.get_address(), method="submitTransaction", params=params)
        signed_transaction = SignedTransaction(tx, from_)

        tx_hash = self._icon_service.send_transaction(signed_transaction)
        tx_result = self._getTXResult(tx_hash)
        MultiSigBridgeTest.pp.pprint(tx_result)

        return tx_result

    def _getWalletOwners(self) -> dict:
        params = {"_offset": 0,
                  "_count": 10}

        tx = self._buildTransaction(type="read", from_=self._owners[0].get_address(), method="getWalletOwners",
                                    params=params)

        return self._icon_service.call(tx)

    def _getTXList(self) -> dict:
        params = {"_offset": "0x0",
                  "_count": "0xa",
                  "_pending": "0x1",
                  "_executed": "0x1"}

        tx = self._buildTransaction(type="read", from_=self._owners[0].get_address(), method="getTransactionList",
                                    params=params)

        return self._icon_service.call(tx)

if __name__ == '__main__':
    unittest.main()
