import unittest,time
from types import SimpleNamespace
from unittest.mock import patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from app.security import delegation
from fastapi import HTTPException

class DelegationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    def claims(self,**changes):
        now=int(time.time());return dict(iss='easyjob-blog',aud='easyjob-agent',sub='7',iat=now,nbf=now-1,exp=now+60,jti='test',token_use='delegation',sid='a'*64,ver=2,**changes)
    def check(self,claims,method='Chat'):
        token=jwt.encode(claims,self.key,algorithm='RS256')
        with patch.object(delegation.settings,'AUTH_DELEGATION_ENABLED',True),patch.object(delegation,'public_key',return_value=self.key.public_key()):return delegation.verify(SimpleNamespace(user_id=7,delegation_token=token),method)
    def tearDown(self):delegation.current_identity.set(None)
    def test_valid_delegation_binds_authenticated_user(self):self.check(self.claims());self.assertEqual(delegation.current_identity.get(),dict(user_id=7,sid='a'*64,version=2))
    def test_wrong_user_audience_and_expiry_are_rejected(self):
        for changes in [dict(sub='8'),dict(aud='other'),dict(exp=int(time.time())-20)]:
            claims=self.claims();claims.update(changes)
            with self.assertRaises(HTTPException):self.check(claims)
    def test_service_observation_cannot_start_chat(self):
        claims=self.claims();claims['token_use']='service_observe'
        with self.assertRaises(HTTPException):self.check(claims)
        self.assertEqual(self.check(claims,'ServiceQuery'),'service_observe')
    def test_missing_session_does_not_authorize_user(self):
        claims=self.claims();del claims['sid']
        with self.assertRaises(HTTPException):self.check(claims)

    def test_run_config_restores_persisted_identity_but_preserves_current_session(self):
        from app.services.run_service import RunService
        run = dict(run_id='test-run', execution_token='executor', user_id=7,
                   auth_sid='a'*64, auth_version=2)
        with patch.object(delegation.settings, 'AUTH_DELEGATION_ENABLED', True):
            config = RunService.config(run)
            self.assertEqual(config['configurable']['thread_id'], 'run_test-run')
            self.assertEqual(delegation.current_identity.get(), dict(user_id=7, sid='a'*64, version=2))
            current = dict(user_id=7, sid='b'*64, version=3)
            delegation.current_identity.set(current)
            RunService.config(run)
            self.assertEqual(delegation.current_identity.get(), current)
