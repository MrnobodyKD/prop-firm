"""NOWPayments adapter for the crypto payment rail."""
import hashlib
import hmac
import json
import os

import requests


DEFAULT_API_BASE_URL = 'https://api-sandbox.nowpayments.io/v1'


def _api_base_url():
    return os.getenv('NOWPAYMENTS_API_BASE_URL', DEFAULT_API_BASE_URL).rstrip('/')


def _api_key():
    key = os.getenv('NOWPAYMENTS_API_KEY', '').strip()
    if not key:
        raise RuntimeError('NOWPayments API is not configured.')
    return key


def _headers():
    return {'x-api-key': _api_key(), 'Content-Type': 'application/json'}


def create_invoice(price_amount, order_id, ipn_callback_url, success_url, cancel_url, order_description='Challenge purchase'):
    """Create a hosted NOWPayments invoice using the documented POST /invoice API."""
    payload = {
        'price_amount': round(float(price_amount), 2),
        'price_currency': 'usd',
        'pay_currency': 'usdttrc20',
        'order_id': str(order_id),
        'order_description': order_description,
        'ipn_callback_url': ipn_callback_url,
        'success_url': success_url,
        'cancel_url': cancel_url,
    }
    response = requests.post(f'{_api_base_url()}/invoice', headers=_headers(), json=payload, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not data.get('id') or not data.get('invoice_url'):
        raise RuntimeError('NOWPayments did not return an invoice ID and URL.')
    return data


def verify_ipn(payload, signature):
    """Verify x-nowpayments-sig using sorted JSON keys and HMAC-SHA512."""
    secret = os.getenv('NOWPAYMENTS_IPN_SECRET', '').strip()
    if not secret or not signature or not isinstance(payload, dict):
        return False
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    expected = hmac.new(secret.encode('utf-8'), canonical.encode('utf-8'), hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected.lower(), signature.strip().lower())


def get_payment_status(payment_id):
    """Recheck a payment server-to-server using GET /payment/{payment_id}."""
    response = requests.get(
        f'{_api_base_url()}/payment/{payment_id}',
        headers={'x-api-key': _api_key()},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()
