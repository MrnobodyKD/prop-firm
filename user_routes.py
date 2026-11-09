from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, abort, current_app, send_from_directory
from functools import wraps
from models import db, User, ChallengeTemplate, ChallengePurchase, Payment, PaymentMethod, PurchaseRuleAcceptance, Payout, PayoutAuditLog, SupportTicket, TicketMessage, FAQ, TradeHistory, Notification, UserNotification, Coupon, CouponUsage, CouponAssignment, ProgressionRequest, RulebookSection, Wallet, WalletTransaction, WithdrawalRequest, SurveyAssignment, SurveyResponse, ViolationEvidence, SiteSettings
from datetime import datetime, timezone, timedelta
import os
import secrets
import random
import json
import uuid
from werkzeug.utils import secure_filename

# ===== FIX: Handle PIL import gracefully =====
try:
    from PIL import Image
    HAS_PIL = True
    # Check for Resampling attribute (PIL 9.0+)
    try:
        RESAMPLING_METHOD = Image.Resampling.LANCZOS
    except AttributeError:
        RESAMPLING_METHOD = Image.LANCZOS
except ImportError:
    HAS_PIL = False
    print("[WARNING] PIL/Pillow not installed. Image processing will be disabled.")
    # Create a dummy Image class to prevent errors
    class DummyImage:
        @staticmethod
        def open(*args, **kwargs):
            raise NotImplementedError("PIL/Pillow is not installed. Please install it with: pip install Pillow")
        class Resampling:
            LANCZOS = 1
    Image = DummyImage
    RESAMPLING_METHOD = 1

import time
from notification_service import create_notification

user_bp = Blueprint('user', __name__, url_prefix='/user')

ACTIVE_PAYOUT_STATUSES = ['pending', 'under_review', 'approved']
ACTIVE_CHALLENGE_STATUSES = ['active', 'funded', 'phase1_active', 'phase2_active', 'funded_active']
HISTORY_CHALLENGE_STATUSES = ['passed', 'failed', 'inactive', 'under_review']
COMPLIANCE_REVIEW_MESSAGE = 'Your account is currently under compliance review. You will be notified once the review is complete.'
_INTERNAL_MESSAGE_TERMS = (
    'admin',
    'audit',
    'database',
    'evidence generated',
    'internal log',
    'rule engine',
    'system message',
)

def compress_and_save_ticket_attachment(attachment, ticket_number, prefix=""):
    if not HAS_PIL:
        # If PIL is not available, save without compression
        ext = attachment.filename.rsplit('.', 1)[1].lower() if '.' in attachment.filename else ''
        if ext not in {'png', 'jpg', 'jpeg', 'pdf'}:
            return None
            
        upload_dir = os.path.join('static', 'uploads', 'tickets')
        os.makedirs(upload_dir, exist_ok=True)
        
        filename = secure_filename(f"{prefix}{ticket_number}_{int(time.time())}_{attachment.filename}")
        target_path = os.path.join(upload_dir, filename)
        attachment.save(target_path)
        return f"uploads/tickets/{filename}"
    
    ext = attachment.filename.rsplit('.', 1)[1].lower() if '.' in attachment.filename else ''
    if ext not in {'png', 'jpg', 'jpeg', 'pdf'}:
        return None
        
    upload_dir = os.path.join('static', 'uploads', 'tickets')
    os.makedirs(upload_dir, exist_ok=True)
    
    if ext in {'png', 'jpg', 'jpeg'}:
        filename = secure_filename(f"{prefix}{ticket_number}_{int(time.time())}.jpg")
        target_path = os.path.join(upload_dir, filename)
        
        img = Image.open(attachment)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        max_width = 1200
        if img.width > max_width:
            ratio = max_width / float(img.width)
            height = int(float(img.height) * ratio)
            img = img.resize((max_width, height), RESAMPLING_METHOD)
        
        img.save(target_path, "JPEG", quality=65, optimize=True)
        return f"uploads/tickets/{filename}"
    elif ext == 'pdf':
        filename = secure_filename(f"{prefix}{ticket_number}_{int(time.time())}_{attachment.filename}")
        target_path = os.path.join(upload_dir, filename)
        attachment.save(target_path)
        return f"uploads/tickets/{filename}"
    return None

def _is_under_compliance_review(challenge):
    return (
        challenge.status == 'under_review'
        or challenge.monitoring_status == 'under_review'
        or bool(challenge.review_required)
    )

def _safe_public_text(text, fallback='A compliance rule was not met for this challenge.'):
    value = (text or '').strip()
    if not value:
        return fallback
    lowered = value.lower()
    if any(term in lowered for term in _INTERNAL_MESSAGE_TERMS):
        return fallback
    return value

def _public_trade_rows(rows):
    public_rows = []
    for row in rows or []:
        public_rows.append({
            'ticket': row.get('ticket'),
            'symbol': row.get('symbol'),
            'type': row.get('type'),
            'lots': row.get('lots'),
            'open_price': row.get('open_price'),
            'close_price': row.get('close_price'),
            'current_price': row.get('current_price'),
            'sl': row.get('sl'),
            'tp': row.get('tp'),
            'profit': row.get('profit'),
            'floating_pnl': row.get('floating_pnl'),
            'open_time': row.get('open_time'),
            'close_time': row.get('close_time'),
        })
    return public_rows

def _confirmed_user_evidence(challenge_id):
    return ViolationEvidence.query.filter_by(
        challenge_purchase_id=challenge_id,
        is_reviewed=True,
        review_decision='confirmed_fail'
    ).order_by(ViolationEvidence.reviewed_at.desc(), ViolationEvidence.created_at.desc()).all()

def _user_evidence_report(evidence):
    return {
        'failure_reason': _safe_public_text(evidence.reason),
        'rule_broken': _safe_public_text(evidence.rule_name, 'Trading rule'),
        'violation_time': evidence.violation_timestamp.isoformat() if evidence.violation_timestamp else None,
        'violation_time_display': evidence.violation_timestamp.strftime('%d %b %Y %H:%M') if evidence.violation_timestamp else 'N/A',
        'rule_limit': evidence.rule_limit,
        'actual_value': evidence.actual_value,
        'drawdown_model': evidence.drawdown_model,
        'balance': evidence.balance,
        'equity': evidence.equity,
        'floating_pnl': evidence.floating_pnl,
        'daily_drawdown': evidence.daily_drawdown,
        'overall_drawdown': evidence.overall_drawdown,
        'trading_days': evidence.trading_days,
        'open_positions': _public_trade_rows(evidence.open_positions_snapshot),
        'recent_trades': _public_trade_rows(evidence.recent_trades_snapshot),
        'review_notes': _safe_public_text(evidence.review_notes, 'Reviewed and confirmed by the compliance team.'),
    }

def _cycle_days(cycle):
    cycle = (cycle or '').lower()
    if cycle in ['weekly', 'week', '7_days']:
        return 7
    if cycle in ['monthly', 'month']:
        return 30
    return 14

def _aware(dt):
    if not dt:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def _payout_notification(user_id, title, message):
    create_notification(user_id, title, message, 'payout', action_url='/payouts')

def _user_notification(user_id, title, message):
    create_notification(user_id, title, message, 'system')

def _wants_json():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in (request.headers.get('Accept') or '')

def _json_or_redirect(success, message, endpoint='user.dashboard', category='success', status=200):
    if _wants_json():
        return jsonify({'success': success, 'message': message, 'redirect_url': url_for(endpoint)}), status
    flash(message, category)
    return redirect(url_for(endpoint))

def _wallet_credit(user_id, amount, source, reference_type='', reference_id=None, notes=''):
    amount = round(float(amount or 0), 2)
    if amount <= 0:
        return None
    wallet = Wallet.get_or_create(user_id)
    wallet.current_balance = round(float(wallet.current_balance or 0) + amount, 2)
    wallet.lifetime_earned = round(float(wallet.lifetime_earned or 0) + amount, 2)
    tx = WalletTransaction(
        wallet_id=wallet.id,
        user_id=user_id,
        amount=amount,
        transaction_type='credit',
        source=source,
        reference_type=reference_type,
        reference_id=reference_id,
        notes=notes
    )
    db.session.add(tx)
    db.session.flush()
    return tx

def payout_account_type(challenge):
    if challenge.challenge_type == 'instant':
        return 'Instant Funding Account'
    if challenge.status in ['funded', 'funded_active']:
        return 'Funded Account'
    return (challenge.status or 'Challenge').replace('_', ' ').title()

def payout_eligibility(challenge):
    template = challenge.challenge_template
    account_size = float(template.account_size if template else challenge.starting_balance or challenge.current_balance or 0)
    profit_share = float(template.user_profit_share if template else 0)
    minimum_percent = template.min_payout_percent if template and template.min_payout_percent is not None else 5
    minimum = round(account_size * (float(minimum_percent) / 100.0), 2)
    is_funded = challenge.status in ['funded', 'funded_active'] or challenge.challenge_type == 'instant'
    if not is_funded or challenge.status in ['active', 'passed', 'pending_phase2', 'pending_funded', 'phase1_active', 'phase2_active', 'failed', 'expired', 'revoked']:
        return {
            'eligible': False,
            'reason': 'Only Instant Funding Accounts and Funded Accounts can request payouts.',
            'account_size': account_size,
            'minimum': minimum,
            'available_profit': 0.0,
            'profit_share': profit_share,
            'next_date': None,
            'cycle_days': _cycle_days(template.payout_cycle if template else None),
            'account_type': payout_account_type(challenge)
        }

    funded_at = _aware(challenge.funded_at or challenge.start_date or challenge.purchase_date or challenge.created_at)
    cycle_days = _cycle_days(template.payout_cycle if template else None)
    cycle_start = funded_at or _aware(challenge.created_at) or datetime.now(timezone.utc)
    last_completed = Payout.query.filter(
        Payout.challenge_purchase_id == challenge.id,
        Payout.status == 'paid'
    ).order_by(Payout.updated_at.desc()).first()
    if last_completed:
        cycle_start = _aware(last_completed.paid_at or last_completed.updated_at or last_completed.created_at) or cycle_start
    first_days = template.first_withdrawal_days if template and template.first_withdrawal_days is not None else cycle_days
    next_date = cycle_start + timedelta(days=(cycle_days if last_completed else first_days))

    active_request = Payout.query.filter(
        Payout.challenge_purchase_id == challenge.id,
        Payout.status.in_(ACTIVE_PAYOUT_STATUSES)
    ).first()

    baseline = float(challenge.phase_start_balance or challenge.starting_balance or account_size or 0)
    current_value = float(challenge.current_equity or challenge.current_balance or baseline)
    funded_profit = max(0.0, current_value - baseline)
    paid_amount = db.session.query(db.func.coalesce(db.func.sum(Payout.amount), 0)).filter(
        Payout.challenge_purchase_id == challenge.id,
        Payout.status == 'paid'
    ).scalar() or 0
    available_profit = round(max(0.0, (funded_profit * (profit_share / 100.0)) - float(paid_amount)), 2)

    now = datetime.now(timezone.utc)
    eligible = True
    reason = ''
    if active_request:
        eligible = False
        reason = 'A payout request is already active for this account.'
    elif available_profit < minimum:
        eligible = False
        reason = 'Minimum payout threshold not reached.'
    elif now < next_date:
        eligible = False
        reason = f"Next payout date: {next_date.strftime('%d %B %Y')}"

    return {
        'eligible': eligible,
        'reason': reason,
        'account_size': account_size,
        'minimum': minimum,
        'available_profit': available_profit,
        'profit_share': profit_share,
        'next_date': next_date,
        'cycle_days': cycle_days,
        'account_type': payout_account_type(challenge),
        'active_request': active_request
    }

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

# ===== DASHBOARD ROUTES =====
@user_bp.route('/dashboard')
@login_required
def dashboard():
    user_id = session.get('user_id')
    if not user_id:
        flash('Please login again.', 'error')
        return redirect(url_for('auth.login'))
    
    user = User.query.get(user_id)
    if not user:
        flash('User not found. Please login again.', 'error')
        session.clear()
        return redirect(url_for('auth.login'))
    
    # Get user's active challenges (compact, limited to 3)
    active_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status.in_(ACTIVE_CHALLENGE_STATUSES)
    ).order_by(ChallengePurchase.created_at.desc()).limit(3).all()
    
    # Calculate days remaining
    now_utc = datetime.now(timezone.utc)
    for challenge in active_challenges:
        if challenge.challenge_template and challenge.challenge_template.no_expiry:
            challenge.days_remaining = None
        elif challenge.end_date:
            end_date = challenge.end_date.replace(tzinfo=timezone.utc) if challenge.end_date.tzinfo is None else challenge.end_date
            days_left = (end_date - now_utc).days
            challenge.days_remaining = max(0, days_left)
        else:
            challenge.days_remaining = 0
        
        if challenge.current_profit is None:
            challenge.current_profit = 0.0
        if challenge.progress_percentage is None:
            challenge.progress_percentage = 0.0
        if challenge.max_drawdown_used is None:
            challenge.max_drawdown_used = 0.0
    
    # Available challenges for purchase (limit 3)
    available_challenges = ChallengeTemplate.query.filter_by(is_active=True).order_by(ChallengeTemplate.price).limit(3).all()
    
    # Pending payouts count
    pending_payouts_count = Payout.query.filter(
        Payout.user_id == user.id,
        Payout.status.in_(ACTIVE_PAYOUT_STATUSES)
    ).count()
    
    # Open tickets
    open_tickets = SupportTicket.query.filter_by(user_id=user.id, status='open').order_by(SupportTicket.updated_at.desc()).limit(3).all()
    
    # Active coupons count
    now = datetime.now(timezone.utc)
    active_coupons = Coupon.query.filter_by(is_active=True, is_deleted=False).all()
    active_coupons_count = 0
    for coupon in active_coupons:
        if coupon.expires_at:
            expires_at = coupon.expires_at.replace(tzinfo=timezone.utc) if coupon.expires_at.tzinfo is None else coupon.expires_at
            if expires_at < now:
                continue
        used = CouponUsage.query.filter_by(coupon_id=coupon.id, user_id=user.id).first()
        if used:
            continue
        if coupon.coupon_type == 'universal':
            if coupon.max_uses is None or coupon.used_count < coupon.max_uses:
                active_coupons_count += 1
        elif coupon.coupon_type == 'specific':
            assignment = CouponAssignment.query.filter_by(coupon_id=coupon.id, user_id=user.id, is_used=False).first()
            if assignment:
                active_coupons_count += 1
    
    all_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status.in_(HISTORY_CHALLENGE_STATUSES)
    ).order_by(ChallengePurchase.created_at.desc()).limit(5).all()
    progression_requests = ProgressionRequest.query.filter_by(user_id=user.id).order_by(ProgressionRequest.created_at.desc()).limit(5).all()
    progression_eligible_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status == 'passed',
        ChallengePurchase.current_phase.in_([1, 2, 3])
    ).order_by(ChallengePurchase.completed_at.desc().nullslast()).all()
    
    return render_template('user/user_dashboard.html',
                         user=user, 
                         active_challenges=active_challenges,
                         available_challenges=available_challenges,
                         pending_payouts_count=pending_payouts_count,
                         open_tickets=open_tickets,
                         active_coupons_count=active_coupons_count,
                         all_challenges=all_challenges,
                         progression_requests=progression_requests,
                         progression_eligible_challenges=progression_eligible_challenges,
                         SupportTicket=SupportTicket)

@user_bp.route('/dashboard/stats')
@login_required
def dashboard_stats():
    """API endpoint for dashboard statistics"""
    user = User.query.get(session['user_id'])
    
    active_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status.in_(ACTIVE_CHALLENGE_STATUSES)
    ).all()
    
    total_balance = sum(c.current_balance or 0 for c in active_challenges)
    total_profit = sum(c.current_profit or 0 for c in active_challenges)
    
    stats = {
        'account_balance': total_balance,
        'current_profit': total_profit,
        'active_challenges_count': len(active_challenges),
        'drawdown_used': max([c.max_drawdown_used or 0 for c in active_challenges], default=0),
        'days_remaining': min([c.days_remaining or 30 for c in active_challenges], default=30),
    }
    
    return jsonify({'success': True, 'stats': stats})

@user_bp.route('/phone-verification')
@login_required
def phone_verification():
    user = User.query.get(session['user_id'])
    return render_template('user/phone_verification.html', user=user)


# ===== CHALLENGE ROUTES =====
@user_bp.route('/buy_challenges')
@login_required
def user_challenges():
    user = User.query.get(session['user_id'])
    user_purchases = ChallengePurchase.query.filter_by(user_id=user.id).join(ChallengeTemplate).all()
    
    # Get available challenges
    available_challenges = ChallengeTemplate.query.filter_by(is_active=True).order_by(ChallengeTemplate.price).all()
    
    return render_template('user/user_challenges.html', 
                         user=user, 
                         purchases=user_purchases,
                         challenges=available_challenges)

@user_bp.route('/rulebook')
@login_required
def rulebook():
    user = User.query.get(session['user_id'])
    sections = RulebookSection.query.filter_by(is_active=True).order_by(
        RulebookSection.display_order.asc(),
        RulebookSection.id.asc()
    ).all()
    return render_template('user/rulebook.html', user=user, sections=sections)

@user_bp.route('/challenge/<int:challenge_id>/buy')
@login_required
def buy_challenge(challenge_id):
    user = User.query.get_or_404(session['user_id'])
    challenge = ChallengeTemplate.query.get_or_404(challenge_id)

    # 🔒 CHECK MARKETPLACE LOCKDOWN
    settings = SiteSettings.get_settings()
    if settings.marketplace_locked:
        flash('🔒 Purchases are temporarily disabled. ' + (settings.marketplace_lock_reason or 'Please check back later.'), 'error')
        return redirect(url_for('user.challenges'))

    if not challenge.is_active:
        flash('This challenge is currently unavailable.', 'error')
        return redirect(url_for('user.challenges'))

    payment_methods = PaymentMethod.query.filter_by(is_active=True).order_by(PaymentMethod.sort_order, PaymentMethod.name).all()

    return render_template(
        'user/buy_challenge.html',
        user=user,
        challenge=challenge,
        payment_methods=payment_methods,
        nowpayments_enabled=bool(os.getenv('NOWPAYMENTS_API_KEY'))
    )


def _checkout_coupon_price(user, challenge, code):
    price = float(challenge.price)
    if not code:
        return price
    coupon = Coupon.query.filter_by(code=code.upper().strip(), is_deleted=False).first()
    if not coupon:
        raise ValueError('Invalid coupon code')
    challenge_currency = (challenge.currency or 'USD').upper()
    if (coupon.currency or challenge_currency).upper() != challenge_currency:
        raise ValueError(f'This coupon is in {(coupon.currency or challenge_currency).upper()}; the challenge is priced in {challenge_currency}.')
    valid, message, _discount, discounted_price = coupon.validate_for_user_and_price(user.id, price)
    if not valid:
        raise ValueError(message)
    return float(discounted_price)


def _purchase_guard(user, challenge):
    settings = SiteSettings.get_settings()
    if settings.marketplace_locked:
        raise ValueError(settings.marketplace_lock_reason or 'Purchases are temporarily disabled.')
    if not challenge.is_active:
        raise ValueError('This challenge is currently unavailable.')
    active = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status.in_(['active', 'phase1_active', 'phase2_active', 'funded', 'funded_active', 'pending_phase2', 'pending_funded', 'pending_credentials', 'passed', 'under_review', 'flagged', 'offline'])
    ).count()
    if challenge.max_accounts_per_user is not None and active >= challenge.max_accounts_per_user:
        raise ValueError(f'Maximum of {challenge.max_accounts_per_user} active or funded accounts reached.')


@user_bp.route('/manual-payment/<int:challenge_id>/<int:method_id>', methods=['GET', 'POST'])
@login_required
def manual_payment(challenge_id, method_id):
    user = User.query.get_or_404(session['user_id'])
    challenge = ChallengeTemplate.query.get_or_404(challenge_id)
    method = PaymentMethod.query.filter_by(id=method_id, is_active=True).first_or_404()
    try:
        _purchase_guard(user, challenge)
        coupon_code = request.values.get('coupon_code', '').strip()
        final_price = _checkout_coupon_price(user, challenge, coupon_code)
        amount_local = round(final_price / method.exchange_rate_to_usd, 2) if method.exchange_rate_to_usd else None
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('user.challenges'))

    if request.method == 'POST':
        if request.form.get('terms_acknowledgement') != 'on' or request.form.get('rule_acknowledgement') != 'on':
            flash('Accept the terms and challenge rules before submitting proof.', 'error')
            return render_template('user/manual_payment.html', user=user, challenge=challenge, method=method, amount=final_price, amount_local=amount_local, coupon_code=coupon_code)
        transaction_id = request.form.get('transaction_id', '').strip()
        message = request.form.get('message', '').strip()
        upload = request.files.get('evidence')
        if not transaction_id or len(transaction_id) > 160 or not upload or not upload.filename:
            flash('Add the transaction reference and payment screenshot.', 'error')
            return render_template('user/manual_payment.html', user=user, challenge=challenge, method=method, amount=final_price, amount_local=amount_local, coupon_code=coupon_code)
        data = upload.read(5 * 1024 * 1024 + 1)
        upload.stream.seek(0)
        extension = secure_filename(upload.filename).rsplit('.', 1)[-1].lower() if '.' in upload.filename else ''
        normalized_extension = 'jpg' if extension == 'jpeg' else extension
        signatures = {'png': b'\x89PNG\r\n\x1a\n', 'jpg': b'\xff\xd8\xff', 'gif': b'GIF8', 'webp': b'RIFF'}
        detected = next((ext for ext, header in signatures.items() if data.startswith(header) and (ext != 'webp' or data[8:12] == b'WEBP')), None)
        if len(data) > 5 * 1024 * 1024 or detected is None or detected != normalized_extension:
            flash('Upload a valid PNG, JPEG, GIF, or WebP screenshot no larger than 5 MB.', 'error')
            return render_template('user/manual_payment.html', user=user, challenge=challenge, method=method, amount=final_price, amount_local=amount_local, coupon_code=coupon_code)

        evidence_name = f'{uuid.uuid4().hex}.{detected}'
        evidence_dir = os.path.join(current_app.instance_path, 'payment_evidence')
        os.makedirs(evidence_dir, exist_ok=True)
        with open(os.path.join(evidence_dir, evidence_name), 'wb') as evidence_file:
            evidence_file.write(data)
        payment = Payment(
            user_id=user.id,
            payment_id=f'MAN-{uuid.uuid4().hex}',
            amount=final_price,
            expected_amount=final_price,
            currency='USD',
            payment_method=method.name,
            gateway='manual',
            challenge_template_id=challenge.id,
            status='pending',
            payment_method_type='manual',
            payment_method_id=method.id,
            method_name=method.name,
            external_reference=transaction_id,
            evidence_path=evidence_name,
            amount_local=amount_local,
            local_currency=method.currency if amount_local is not None else None,
            gateway_status='manual_claim_submitted',
            gateway_message=message,
            coupon_id=Coupon.query.filter_by(code=coupon_code.upper(), is_deleted=False).first().id if coupon_code else None,
            rule_acceptance_timestamp=datetime.now(timezone.utc),
            rule_acceptance_ip=request.headers.get('X-Forwarded-For', request.remote_addr),
            rule_acceptance_user_agent=request.headers.get('User-Agent'),
            challenge_version_snapshot=challenge.rule_snapshot(),
            rule_version_snapshot='rulebook-v1',
        )
        db.session.add(payment)
        db.session.flush()
        db.session.add(PurchaseRuleAcceptance(
            user_id=user.id,
            challenge_template_id=challenge.id,
            payment_id=payment.id,
            accepted_at=payment.rule_acceptance_timestamp,
            ip_address=payment.rule_acceptance_ip,
            user_agent=payment.rule_acceptance_user_agent,
            challenge_version_snapshot=payment.challenge_version_snapshot,
            rule_version_snapshot=payment.rule_version_snapshot,
        ))
        db.session.commit()
        flash('Payment proof submitted. Your challenge will be created after an admin verifies the payment.', 'success')
        return redirect(url_for('user.payment_status_page', payment_id=payment.id))

    return render_template('user/manual_payment.html', user=user, challenge=challenge, method=method, amount=final_price, amount_local=amount_local, coupon_code=coupon_code)


@user_bp.route('/crypto-payment', methods=['POST'])
@login_required
def crypto_payment_start():
    user = User.query.get_or_404(session['user_id'])
    challenge = ChallengeTemplate.query.get_or_404(request.form.get('challenge_id', type=int))
    if request.form.get('terms_acknowledgement') != 'on' or request.form.get('rule_acknowledgement') != 'on':
        flash('Accept the terms and challenge rules before continuing.', 'error')
        return redirect(url_for('user.buy_challenge', challenge_id=challenge.id))
    try:
        _purchase_guard(user, challenge)
        coupon_code = request.form.get('coupon_code', '').strip()
        final_price = _checkout_coupon_price(user, challenge, coupon_code)
        if (challenge.currency or 'USD').upper() != 'USD':
            raise ValueError('Crypto checkout currently requires a USD challenge price.')
        from crypto_gateway import create_invoice
        payment = Payment(
            user_id=user.id,
            payment_id=f'NP-{uuid.uuid4().hex}',
            amount=final_price,
            expected_amount=final_price,
            currency='USD',
            payment_method='crypto',
            gateway='nowpayments',
            challenge_template_id=challenge.id,
            status='waiting',
            payment_method_type='nowpayments',
            method_name='NOWPayments',
            coupon_id=Coupon.query.filter_by(code=coupon_code.upper(), is_deleted=False).first().id if coupon_code else None,
            rule_acceptance_timestamp=datetime.now(timezone.utc),
            rule_acceptance_ip=request.headers.get('X-Forwarded-For', request.remote_addr),
            rule_acceptance_user_agent=request.headers.get('User-Agent'),
            challenge_version_snapshot=challenge.rule_snapshot(),
            rule_version_snapshot='rulebook-v1',
        )
        db.session.add(payment)
        db.session.flush()
        invoice = create_invoice(
            final_price,
            payment.payment_id,
            url_for('nowpayments_webhook', _external=True),
            url_for('payment_success', order_id=payment.payment_id, _external=True),
            url_for('payment_status', payment_id=payment.id, _external=True),
            order_description=challenge.name,
        )
        payment.gateway_order_id = str(invoice['id'])
        payment.invoice_url = invoice['invoice_url']
        payment.gateway_status = str(invoice.get('payment_status', 'waiting'))
        invoice_expiry = invoice.get('expiration_estimate_date') or invoice.get('expires_at') or invoice.get('expiration_date')
        if invoice_expiry:
            payment.expires_at = datetime.fromisoformat(str(invoice_expiry).replace('Z', '+00:00'))
        else:
            payment.expires_at = None
        db.session.commit()
        return redirect(invoice['invoice_url'])
    except Exception as exc:
        db.session.rollback()
        flash(str(exc) if isinstance(exc, ValueError) else 'Crypto checkout is currently unavailable. Please try again.', 'error')
        return redirect(url_for('user.buy_challenge', challenge_id=challenge.id))


@user_bp.route('/payment-status/<int:payment_id>')
@login_required
def payment_status_page(payment_id):
    payment = Payment.query.filter_by(id=payment_id, user_id=session['user_id']).first_or_404()
    return render_template('user/payment_status.html', user=User.query.get(session['user_id']), payment=payment, challenge=payment.challenge_purchase, status=payment.status)


@user_bp.route('/payment-evidence/<int:payment_id>')
@login_required
def payment_evidence(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    viewer = User.query.get(session['user_id'])
    if payment.user_id != viewer.id and not viewer.is_admin:
        abort(404)
    if not payment.evidence_path or os.path.basename(payment.evidence_path) != payment.evidence_path:
        abort(404)
    return send_from_directory(os.path.join(current_app.instance_path, 'payment_evidence'), payment.evidence_path)


@user_bp.route('/payment-method-image/<int:method_id>/<image_kind>')
@login_required
def payment_method_image(method_id, image_kind):
    method = PaymentMethod.query.get_or_404(method_id)
    viewer = User.query.get(session['user_id'])
    if not method.is_active and not viewer.is_admin:
        abort(404)
    filename = method.qr_image if image_kind == 'qr' else method.help_image if image_kind == 'help' else None
    if not filename or os.path.basename(filename) != filename:
        abort(404)
    return send_from_directory(os.path.join(current_app.instance_path, 'payment_method_assets'), filename)

# ===== TRADING ROUTES =====
@user_bp.route('/trading')
@login_required
def trading():
    user = User.query.get(session['user_id'])
    active_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status.in_(ACTIVE_CHALLENGE_STATUSES)
    ).join(ChallengeTemplate).all()
    
    now_utc = datetime.now(timezone.utc)
    for challenge in active_challenges:
        if challenge.challenge_template and challenge.challenge_template.no_expiry:
            challenge.days_remaining = None
        elif challenge.end_date:
            end_date = challenge.end_date.replace(tzinfo=timezone.utc) if challenge.end_date.tzinfo is None else challenge.end_date
            days_left = (end_date - now_utc).days
            challenge.days_remaining = max(0, days_left)
        else:
            challenge.days_remaining = 0
    
    return render_template('user/trading.html',
                         user=user,
                         active_challenges=active_challenges)

@user_bp.route('/challenge/<int:challenge_id>/rules')
@login_required
def challenge_rules(challenge_id):
    user = User.query.get(session['user_id'])
    challenge = ChallengePurchase.query.filter_by(id=challenge_id, user_id=user.id).first_or_404()
    phase_rules = challenge.challenge_template.get_phase_rules(challenge.current_phase) if challenge.challenge_template else {}
    return render_template('user/challenge_rules.html', user=user, challenge=challenge, rules=phase_rules)

@user_bp.route('/history')
@login_required
def user_history():
    user = User.query.get(session['user_id'])
    pending_crypto = Payment.query.filter_by(user_id=user.id, payment_method_type='nowpayments', status='waiting').all()
    now = datetime.now(timezone.utc)
    for payment in pending_crypto:
        if payment.expires_at:
            expiry = payment.expires_at.replace(tzinfo=timezone.utc) if payment.expires_at.tzinfo is None else payment.expires_at
            if expiry <= now:
                payment.status = 'expired'
                payment.gateway_status = 'expired'
    if pending_crypto:
        db.session.commit()
    user_payments = Payment.query.filter_by(user_id=user.id).order_by(Payment.created_at.desc()).all()
    for payment in user_payments:
        expiry = payment.expires_at.replace(tzinfo=timezone.utc) if payment.expires_at and payment.expires_at.tzinfo is None else payment.expires_at
        payment.can_continue = bool(payment.status == 'waiting' and payment.invoice_url and (expiry is None or expiry > now))
    purchases = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status.in_(HISTORY_CHALLENGE_STATUSES)
    ).order_by(ChallengePurchase.created_at.desc()).all()
    progression_requests = ProgressionRequest.query.filter_by(user_id=user.id).order_by(ProgressionRequest.created_at.desc()).all()
    
    stats = {
        'total': len(purchases),
        'passed': len([p for p in purchases if p.status == 'passed']),
        'failed': len([p for p in purchases if p.status == 'failed']),
        'active': ChallengePurchase.query.filter(
            ChallengePurchase.user_id == user.id,
            ChallengePurchase.status.in_(ACTIVE_CHALLENGE_STATUSES)
        ).count(),
        'progression_requests': len(progression_requests)
    }
    
    return render_template('user/user_history.html', user=user, purchases=purchases, progression_requests=progression_requests, stats=stats, payments=user_payments, now=now)

@user_bp.route('/trading/history')
@login_required
def trading_history():
    return redirect(url_for('user.user_history'))

@user_bp.route('/mt5-download')
@login_required
def mt5_download():
    return render_template('user/mt5_download.html')

# ===== PROFILE ROUTES =====
@user_bp.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    return render_template('user/profile.html', user=user)

@user_bp.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    try:
        user = User.query.get(session['user_id'])
        user.first_name = request.form.get('first_name', user.first_name)
        user.last_name = request.form.get('last_name', user.last_name)
        user.phone = request.form.get('phone', user.phone)
        
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error updating profile. Please try again.', 'error')
    
    return redirect(url_for('user.profile'))

# ===== PAYMENT & PAYOUT ROUTES =====
@user_bp.route('/payments')
@login_required
def payments():
    user = User.query.get(session['user_id'])
    user_payments = Payment.query.filter_by(user_id=user.id).order_by(Payment.created_at.desc()).all()
    now = datetime.now(timezone.utc)
    changed = False
    for payment in user_payments:
        if payment.payment_method_type == 'nowpayments' and payment.status == 'waiting' and payment.expires_at:
            expiry = payment.expires_at.replace(tzinfo=timezone.utc) if payment.expires_at.tzinfo is None else payment.expires_at
            if expiry <= now:
                payment.status = 'expired'
                payment.gateway_status = 'expired'
                changed = True
    if changed:
        db.session.commit()
    for payment in user_payments:
        expiry = payment.expires_at.replace(tzinfo=timezone.utc) if payment.expires_at and payment.expires_at.tzinfo is None else payment.expires_at
        payment.can_continue = bool(payment.status == 'waiting' and payment.invoice_url and (expiry is None or expiry > now))
    
    return render_template('user/payment_history.html',
                         user=user,
                         payments=user_payments,
                         now=now)

@user_bp.route('/payouts')
@login_required
def payouts():
    user = User.query.get(session['user_id'])
    purchases = ChallengePurchase.query.filter_by(user_id=user.id).order_by(ChallengePurchase.created_at.desc()).all()
    eligible_accounts = []
    blocked_accounts = []
    for purchase in purchases:
        info = payout_eligibility(purchase)
        row = {'challenge': purchase, 'info': info}
        if purchase.status in ['funded', 'funded_active'] or purchase.challenge_type == 'instant':
            eligible_accounts.append(row)
        elif purchase.status in ['active', 'passed', 'failed', 'expired', 'revoked']:
            blocked_accounts.append(row)
    user_payouts = Payout.query.filter_by(user_id=user.id).order_by(Payout.created_at.desc()).all()
    active_payouts_count = sum(1 for payout in user_payouts if payout.status in ACTIVE_PAYOUT_STATUSES)
    
    return render_template('user/payouts.html', 
                         user=user, 
                         payouts=user_payouts,
                         active_payouts_count=active_payouts_count,
                         eligible_accounts=eligible_accounts,
                         blocked_accounts=blocked_accounts)

@user_bp.route('/request-payout', methods=['POST'])
@login_required
def request_payout():
    try:
        user = User.query.get(session['user_id'])
        challenge_id = request.form.get('challenge_id', type=int)
        amount = float(request.form.get('amount', 0))
        payment_method = request.form.get('payment_method', '').strip()
        account_holder_name = request.form.get('account_holder_name', '').strip()
        
        challenge = ChallengePurchase.query.filter_by(
            id=challenge_id,
            user_id=user.id
        ).first()
        
        if not challenge:
            flash('Invalid challenge selected.', 'error')
            return redirect(url_for('user.payouts'))

        info = payout_eligibility(challenge)
        if not info['eligible']:
            flash(info['reason'] or 'This account is not eligible for payout yet.', 'error')
            return redirect(url_for('user.payouts'))
        
        if amount <= 0 or amount < info['minimum'] or amount > info['available_profit']:
            flash('Invalid payout amount.', 'error')
            return redirect(url_for('user.payouts'))

        if payment_method not in ['bank_transfer', 'crypto']:
            flash('Please select a valid payout method.', 'error')
            return redirect(url_for('user.payouts'))

        if payment_method == 'bank_transfer' and not account_holder_name:
            flash('Account holder name is required.', 'error')
            return redirect(url_for('user.payouts'))

        bank_details = {}
        crypto_address = ''
        if payment_method == 'bank_transfer':
            bank_details = {
                'bank_name': request.form.get('bank_name', '').strip(),
                'account_number': request.form.get('account_number', '').strip(),
            'swift_bic': request.form.get('swift_bic', '').strip().upper(),
            'bank_address': request.form.get('bank_address', '').strip()
            }
            if not all(bank_details.values()):
                flash('Please complete all bank transfer fields.', 'error')
                return redirect(url_for('user.payouts'))
        else:
            crypto_address = request.form.get('crypto_address', '').strip()
            if not crypto_address:
                flash('Please enter your crypto payout address.', 'error')
                return redirect(url_for('user.payouts'))
        
        payout = Payout(
            user_id=user.id,
            challenge_purchase_id=challenge.id,
            amount=amount,
            profit_share_percentage=info['profit_share'],
            status='pending',
            username_snapshot=user.get_full_name(),
            challenge_name_snapshot=challenge.challenge_template.name if challenge.challenge_template else 'Challenge',
            account_type_snapshot=info['account_type'],
            account_size_snapshot=info['account_size'],
            available_profit_snapshot=info['available_profit'],
            due_date=info['next_date'],
            payment_method=payment_method,
            account_holder_name=account_holder_name,
            bank_account_details=json.dumps(bank_details) if bank_details else '',
            crypto_address=crypto_address
        )
        
        db.session.add(payout)
        db.session.flush()
        db.session.add(PayoutAuditLog(
            payout_id=payout.id,
            action='request_created',
            notes='User submitted payout request.'
        ))
        create_notification(
            user.id,
            'Payout Request Submitted',
            'Your payout request has been received successfully and is currently under review.',
            'payout',
            action_url='/payouts',
            icon='dollar',
            dedupe_key=f'payout-requested:{payout.id}',
        )
        db.session.commit()
        
        flash('Payout request submitted successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error requesting payout. Please try again.', 'error')
    
    return redirect(url_for('user.payouts'))


@user_bp.route('/progression/request/<int:challenge_id>/<request_type>', methods=['POST'])
@login_required
def request_progression(challenge_id, request_type):
    try:
        user = User.query.get(session['user_id'])
        challenge = ChallengePurchase.query.filter_by(id=challenge_id, user_id=user.id).first_or_404()

        if request_type not in ['phase2', 'phase3', 'funded']:
            flash('Invalid progression request type.', 'error')
            return redirect(url_for('user.dashboard'))

        if challenge.status != 'passed':
            flash('Only passed challenges can request progression.', 'error')
            return redirect(url_for('user.dashboard'))
        if challenge.review_required:
            flash('This challenge requires compliance review before progression.', 'error')
            return redirect(url_for('user.dashboard'))

        if request_type == 'phase2':
            allowed = challenge.challenge_type in ('two_phase', 'three_phase') and challenge.current_phase == 1
            submitted_title = 'Phase 2 Request Submitted'
            submitted_message = 'Your Phase 2 account request is pending admin review.'
        elif request_type == 'phase3':
            allowed = challenge.challenge_type == 'three_phase' and challenge.current_phase == 2
            submitted_title = 'Phase 3 Request Submitted'
            submitted_message = 'Your Phase 3 account request is pending admin review.'
        else:
            allowed = (
                (challenge.challenge_type == 'two_phase' and challenge.current_phase == 2)
                or (challenge.challenge_type == 'three_phase' and challenge.current_phase == 3)
                or (challenge.challenge_type == 'one_phase' and challenge.current_phase == 1)
            )
            submitted_title = 'Funded Request Submitted'
            submitted_message = 'Your funded account request is pending admin review.'

        if not allowed:
            flash('This challenge is not eligible for that progression request.', 'error')
            return redirect(url_for('user.dashboard'))

        existing = ProgressionRequest.query.filter(
            ProgressionRequest.challenge_purchase_id == challenge.id,
            ProgressionRequest.request_type == request_type,
            ProgressionRequest.status == 'pending'
        ).first()
        if existing:
            flash('You already have a pending progression request for this challenge.', 'info')
            return redirect(url_for('user.dashboard'))

        progression_request = ProgressionRequest(
            user_id=user.id,
            challenge_purchase_id=challenge.id,
            request_type=request_type,
            status='pending'
        )
        db.session.add(progression_request)
        _user_notification(user.id, submitted_title, submitted_message)
        db.session.commit()

        flash('Progression request submitted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"Progression request error: {e}")
        flash('Error submitting progression request. Please try again.', 'error')

    return redirect(url_for('user.dashboard'))

# ===== SETTINGS ROUTES =====
@user_bp.route('/settings')
@login_required
def settings():
    user = User.query.get(session['user_id'])
    return render_template('user/settings.html', user=user)

@user_bp.route('/settings/update', methods=['POST'])
@login_required
def update_settings():
    try:
        user = User.query.get(session['user_id'])
        
        if 'trading_alias' in request.form:
            user.trading_alias = request.form.get('trading_alias', '').strip()
            
        if 'is_compact_view' in request.form:
            user.is_compact_view = request.form.get('is_compact_view') == 'true'
            
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error updating settings.', 'error')
    
    return redirect(url_for('user.settings'))

@user_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    try:
        user = User.query.get(session['user_id'])
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not user.check_password(current_password):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('user.settings'))
        
        if new_password != confirm_password:
            flash('New passwords do not match.', 'error')
            return redirect(url_for('user.settings'))
        
        if len(new_password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return redirect(url_for('user.settings'))
        
        user.set_password(new_password)
        db.session.commit()
        
        flash('Password changed successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error changing password. Please try again.', 'error')
    
    return redirect(url_for('user.settings'))

@user_bp.route('/security')
@login_required
def security():
    user = User.query.get(session['user_id'])
    return render_template('user/security.html', user=user)

# ===== API ENDPOINTS FOR DASHBOARD =====
@user_bp.route('/api/challenge-progress/<int:challenge_id>')
@login_required
def api_challenge_progress(challenge_id):
    challenge = ChallengePurchase.query.filter_by(
        id=challenge_id,
        user_id=session['user_id']
    ).first_or_404()

    if _is_under_compliance_review(challenge):
        return jsonify({
            'success': True,
            'data': {
                'status': 'under_review',
                'review_message': COMPLIANCE_REVIEW_MESSAGE
            }
        })
    
    progress_data = {
        'profit_target_percentage': challenge.progress_percentage or 0,
        'max_drawdown_used': challenge.max_drawdown_used or 0,
        'days_remaining': challenge.days_remaining or 0,
        'current_balance': challenge.current_balance or 0,
        'current_profit': challenge.current_profit or 0,
        'status': challenge.status or 'unknown'
    }
    
    return jsonify({'success': True, 'data': progress_data})

# ===== CHALLENGE ROUTES =====
@user_bp.route('/challenges')
@login_required
def challenges():
    user = User.query.get(session['user_id'])
    settings = SiteSettings.get_settings()
    available_challenges = ChallengeTemplate.query.filter_by(is_active=True).all()
    user_purchases = ChallengePurchase.query.filter_by(user_id=user.id).all()
    
    return render_template('user/user_challenges.html',
                         user=user, 
                         challenges=available_challenges,
                         purchases=user_purchases,
                         settings=settings)

@user_bp.route('/api/challenge/<int:challenge_id>/credentials')
@login_required
def get_challenge_credentials(challenge_id):
    user = User.query.get_or_404(session['user_id'])
    challenge = ChallengePurchase.query.filter_by(
        id=challenge_id,
        user_id=user.id
    ).first_or_404()
    
    return jsonify({
        'success': False,
        'message': 'MT5 credentials are sent by email only and are not shown on the dashboard.'
    }), 403

@user_bp.route('/credentials/<int:challenge_id>')
@login_required
def view_credentials(challenge_id):
    user = User.query.get(session['user_id'])
    
    challenge = ChallengePurchase.query.filter_by(
        id=challenge_id,
        user_id=user.id
    ).first_or_404()
    
    flash('MT5 credentials are sent by email only and are not shown on the dashboard.', 'info')
    return redirect(url_for('user.trading'))

@user_bp.route('/start-phase2/<int:challenge_id>', methods=['POST'])
@login_required
def start_phase2(challenge_id):
    return jsonify({
        'success': False,
        'error': 'Phase 2 accounts must be requested and approved by admin.'
    }), 403
    try:
        user = User.query.get(session['user_id'])
        
        challenge = ChallengePurchase.query.filter_by(
            id=challenge_id,
            user_id=user.id
        ).first_or_404()
        
        if challenge.phase == 2:
            return jsonify({'success': False, 'error': 'Already in Phase 2'})
        
        challenge.phase = 2
        challenge.status = 'phase2_active'
        challenge.start_date = datetime.now(timezone.utc)
        challenge.end_date = datetime.now(timezone.utc) + timedelta(days=30)
        challenge.days_remaining = 30
        challenge.current_profit = 0.0
        challenge.current_loss = 0.0
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Phase 2 started successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@user_bp.route('/trading/dashboard/<int:challenge_id>')
@login_required
def trading_dashboard(challenge_id):
    user = User.query.get(session['user_id'])
    
    challenge = ChallengePurchase.query.filter_by(
        id=challenge_id,
        user_id=user.id
    ).first_or_404()
    
    return render_template('user/user_dashboard.html',
                         user=user,
                         challenge=challenge)

# ===== HELP CENTER & SUPPORT ROUTES =====
@user_bp.route('/help')
@login_required
def help():
    user = User.query.get(session['user_id'])
    search_query = request.args.get('search', '').strip()
    
    if search_query:
        faqs = FAQ.query.filter(
            (FAQ.question.ilike(f'%{search_query}%')) |
            (FAQ.answer.ilike(f'%{search_query}%'))
        ).order_by(FAQ.is_pinned.desc(), FAQ.created_at.desc()).all()
    else:
        faqs = FAQ.query.order_by(FAQ.is_pinned.desc(), FAQ.created_at.desc()).all()
    
    categories = {}
    for faq in faqs:
        if faq.category not in categories:
            categories[faq.category] = []
        categories[faq.category].append(faq)
    
    tickets = SupportTicket.query.filter_by(user_id=user.id).order_by(SupportTicket.updated_at.desc()).all()
    
    return render_template('user/help.html', 
                         user=user, 
                         categories=categories, 
                         tickets=tickets,
                         search_query=search_query)

@user_bp.route('/help/vote', methods=['POST'])
@login_required
def help_vote():
    data = request.get_json()
    faq_id = data.get('faq_id')
    vote = data.get('vote')
    
    faq = FAQ.query.get_or_404(faq_id)
    if vote == 'yes':
        faq.helpful_yes += 1
    elif vote == 'no':
        faq.helpful_no += 1
    
    db.session.commit()
    return jsonify({'success': True})

@user_bp.route('/support/create', methods=['GET', 'POST'])
@login_required
def ticket_create():
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        subject = request.form.get('subject')
        category = request.form.get('category')
        message_text = request.form.get('message')
        attachment = request.files.get('attachment')
        
        if not subject or not category or not message_text:
            flash('All fields are required.', 'error')
            return redirect(url_for('user.ticket_create'))
        
        ticket_number = f"TICK-{int(time.time())}-{random.randint(1000, 9999)}"
        
        ticket = SupportTicket(
            user_id=user.id,
            subject=subject,
            category=category,
            ticket_number=ticket_number,
            status='open'
        )
        
        db.session.add(ticket)
        db.session.flush()
        
        attachment_url = None
        if attachment and attachment.filename != '':
            attachment_url = compress_and_save_ticket_attachment(attachment, ticket_number)
        
        message = TicketMessage(
            ticket_id=ticket.id,
            sender_id=user.id,
            message=message_text,
            is_admin_reply=False,
            attachment_url=attachment_url
        )
        
        db.session.add(message)
        db.session.commit()
        
        flash('Support ticket created successfully!', 'success')
        return redirect(url_for('user.help'))
    
    return render_template('user/ticket_create.html', user=user)

@user_bp.route('/support/ticket/<string:ticket_number>')
@login_required
def ticket_chat(ticket_number):
    user = User.query.get(session['user_id'])
    ticket = SupportTicket.query.filter_by(ticket_number=ticket_number, user_id=user.id).first_or_404()
    
    ticket.last_user_read_at = datetime.now(timezone.utc)
    db.session.commit()
    
    messages = ticket.messages.order_by(TicketMessage.created_at.asc()).all()
    
    return render_template('user/ticket_chat.html', user=user, ticket=ticket, messages=messages)

@user_bp.route('/support/ticket/<string:ticket_number>/reply', methods=['POST'])
@login_required
def ticket_reply(ticket_number):
    user = User.query.get(session['user_id'])
    ticket = SupportTicket.query.filter_by(ticket_number=ticket_number, user_id=user.id).first_or_404()
    
    message_text = request.form.get('message')
    attachment = request.files.get('attachment')
    
    if not message_text and not attachment:
        flash('Message cannot be empty.', 'error')
        return redirect(url_for('user.ticket_chat', ticket_number=ticket_number))
    
    attachment_url = None
    if attachment and attachment.filename != '':
        attachment_url = compress_and_save_ticket_attachment(attachment, ticket_number, prefix="reply_")
    
    message = TicketMessage(
        ticket_id=ticket.id,
        sender_id=user.id,
        message=message_text or "Sent an attachment",
        is_admin_reply=False,
        attachment_url=attachment_url
    )
    
    if ticket.status == 'resolved':
        ticket.status = 'open'
    
    ticket.updated_at = datetime.now(timezone.utc)
    
    db.session.add(message)
    db.session.commit()
    
    return redirect(url_for('user.ticket_chat', ticket_number=ticket_number))

@user_bp.route('/user_analytics')
@login_required
def user_analytics():
    return render_template('user/user_analytics.html', user=User.query.get(session['user_id']))

# ===== CHALLENGE API ROUTES =====
@user_bp.route('/api/challenge/<int:challenge_id>/clear-flag', methods=['POST'])
@login_required
def api_user_clear_flag(challenge_id):
    user = User.query.get(session['user_id'])
    challenge = ChallengePurchase.query.filter_by(id=challenge_id, user_id=user.id).first()
    
    if not challenge:
        return jsonify({'success': False, 'error': 'Challenge not found'}), 404
    
    if not challenge.review_required and challenge.monitoring_status == 'active':
        challenge.status = 'active'
        challenge.monitoring_status = 'active'
        challenge.violation_reason = None
        db.session.commit()
        return jsonify({'success': True, 'message': 'Flag cleared'})
    
    return jsonify({'success': False, 'error': 'Flag cannot be cleared yet'}), 400

@user_bp.route('/history/details/<int:challenge_id>')
@login_required
def history_details(challenge_id):
    user = User.query.get(session['user_id'])
    challenge = ChallengePurchase.query.filter_by(id=challenge_id, user_id=user.id).first_or_404()
    
    evidence_reports = []
    if challenge.status == 'failed':
        evidence_reports = [_user_evidence_report(e) for e in _confirmed_user_evidence(challenge_id)]
    trades = TradeHistory.query.filter_by(challenge_id=challenge_id).order_by(TradeHistory.close_time.desc()).limit(50).all()
    payments = Payment.query.filter_by(challenge_purchase_id=challenge_id, user_id=user.id).order_by(Payment.created_at.desc()).all()
    
    return render_template('user/history_details.html',
                         user=user,
                         challenge=challenge,
                         evidence_reports=evidence_reports,
                         review_message=COMPLIANCE_REVIEW_MESSAGE if _is_under_compliance_review(challenge) else None,
                         payments=payments,
                         trades=trades)

@user_bp.route('/api/challenge/<int:challenge_id>/history')
@login_required
def api_challenge_history(challenge_id):
    user = User.query.get(session['user_id'])
    challenge = ChallengePurchase.query.filter_by(id=challenge_id, user_id=user.id).first()
    
    if not challenge:
        return jsonify({'error': 'Challenge not found'}), 404
    
    evidence_reports = []
    if challenge.status == 'failed':
        evidence_reports = [_user_evidence_report(e) for e in _confirmed_user_evidence(challenge_id)]
    under_review = _is_under_compliance_review(challenge)
    if under_review:
        return jsonify({
            'success': True,
            'challenge': {
                'challenge_name': challenge.challenge_template.name if challenge.challenge_template else 'Challenge',
                'status': 'under_review',
                'review_message': COMPLIANCE_REVIEW_MESSAGE,
            },
            'violations': [],
            'evidence': [],
            'trades': []
        })

    trades = TradeHistory.query.filter_by(challenge_id=challenge_id).order_by(TradeHistory.close_time.desc()).limit(200).all()
    
    return jsonify({
        'success': True,
        'challenge': {
            'challenge_name': challenge.challenge_template.name if challenge.challenge_template else 'Challenge',
            'status': challenge.status,
            'profit_percent': challenge.profit_percent,
            'daily_drawdown': challenge.daily_drawdown,
            'overall_drawdown': challenge.overall_drawdown,
            'trading_days': challenge.trading_days,
            'start_date': challenge.start_date.isoformat() if challenge.start_date else None,
            'end_date': challenge.end_date.isoformat() if challenge.end_date else None,
            'completed_at': challenge.completed_at.isoformat() if challenge.completed_at else None,
            'violation_reason': None if under_review else _safe_public_text(challenge.violation_reason, ''),
            'pass_reason': challenge.pass_reason,
            'review_message': COMPLIANCE_REVIEW_MESSAGE if under_review else None,
        },
        'violations': [],
        'evidence': evidence_reports,
        'trades': [{
            'ticket': t.ticket,
            'symbol': t.symbol,
            'lots': t.lots,
            'profit': t.profit,
            'open_time': t.open_time.isoformat() if t.open_time else None,
            'close_time': t.close_time.isoformat() if t.close_time else None
        } for t in trades]
    })

# ===== MT5 GUIDE ROUTES =====
@user_bp.route('/guide')
def guide_hub():
    return render_template('user/guide.html')

@user_bp.route('/guide/mt5-mobile')
def guide_mt5_mobile():
    return render_template('user/mt5_mobile.html')

@user_bp.route('/guide/mt5_pc')
def guide_mt5_pc():
    return render_template('user/mt5_pc.html')

# ===== FILE TOO LARGE PAGE =====
@user_bp.route('/file-too-large')
@login_required
def file_too_large():
    return render_template('user/file_too_large.html')

# ===== USER NOTIFICATION API ROUTES =====
@user_bp.route('/api/notifications', methods=['GET'])
@login_required
def api_get_notifications():
    try:
        user_id = session.get('user_id')
        now_utc = datetime.now(timezone.utc)

        notifications = Notification.query.filter(
            Notification.is_deleted == False,
            (Notification.expires_at == None) | (Notification.expires_at > now_utc),
            (Notification.is_global == True) | (Notification.target_user_id == user_id)
        ).order_by(Notification.created_at.desc()).all()

        read_mappings = {
            un.notification_id: un.is_read
            for un in UserNotification.query.filter_by(user_id=user_id).all()
        }

        results = []
        for n in notifications:
            is_read = read_mappings.get(n.id, False)
            results.append({
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'type': getattr(n, 'notification_type', 'system') or 'system',
                'created_at': n.created_at.strftime('%Y-%m-%d %H:%M:%S') if n.created_at else '',
                'is_read': is_read,
                'is_global': n.is_global,
                'action_url': n.action_url,
                'icon': n.icon
            })

        unread_count = sum(1 for item in results if not item['is_read'])

        return jsonify({
            'success': True,
            'notifications': results,
            'unread_count': unread_count
        })

    except Exception as e:
        print(f"Error fetching notifications: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve notifications'})


@user_bp.route('/api/notifications/read', methods=['POST'])
@login_required
def api_mark_notifications_read():
    try:
        data = request.get_json() or {}
        notif_ids = data.get('notification_ids', [])
        notif_id = data.get('notification_id')
        
        if notif_id:
            notif_ids.append(notif_id)

        if not notif_ids:
            return jsonify({'success': False, 'error': 'No notification IDs provided'})

        user_id = session.get('user_id')
        now_utc = datetime.now(timezone.utc)

        for nid in notif_ids:
            mapping = UserNotification.query.filter_by(notification_id=nid, user_id=user_id).first()
            if mapping:
                mapping.is_read = True
                mapping.read_at = now_utc
            else:
                notif = Notification.query.filter_by(id=nid, is_deleted=False).first()
                if notif and (notif.is_global or notif.target_user_id == user_id):
                    user_notif = UserNotification(
                        notification_id=nid,
                        user_id=user_id,
                        is_read=True,
                        read_at=now_utc
                    )
                    db.session.add(user_notif)

        db.session.commit()
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        print(f"Error marking notifications read: {e}")
        return jsonify({'success': False, 'error': 'Failed to mark notifications as read'})


@user_bp.route('/api/notifications/read-all', methods=['POST'])
@login_required
def api_mark_all_notifications_read():
    try:
        user_id = session.get('user_id')
        now_utc = datetime.now(timezone.utc)

        notifications = Notification.query.filter(
            Notification.is_deleted == False,
            (Notification.expires_at == None) | (Notification.expires_at > now_utc),
            (Notification.is_global == True) | (Notification.target_user_id == user_id)
        ).all()

        for n in notifications:
            mapping = UserNotification.query.filter_by(notification_id=n.id, user_id=user_id).first()
            if mapping:
                if not mapping.is_read:
                    mapping.is_read = True
                    mapping.read_at = now_utc
            else:
                user_notif = UserNotification(
                    notification_id=n.id,
                    user_id=user_id,
                    is_read=True,
                    read_at=now_utc
                )
                db.session.add(user_notif)

        db.session.commit()
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        print(f"Error marking all notifications read: {e}")
        return jsonify({'success': False, 'error': 'Failed to mark all notifications as read'})


@user_bp.route('/my-coupons')
@login_required
def user_coupons():
    user = User.query.get(session['user_id'])
    now = datetime.now(timezone.utc)
    
    all_coupons = Coupon.query.filter_by(is_active=True, is_deleted=False).all()
    
    available_coupons = []
    for coupon in all_coupons:
        if coupon.expires_at:
            expires_at = coupon.expires_at.replace(tzinfo=timezone.utc) if coupon.expires_at.tzinfo is None else coupon.expires_at
            if expires_at < now:
                continue

        used = CouponUsage.query.filter_by(coupon_id=coupon.id, user_id=user.id).first()
        if used:
            continue
            
        if coupon.coupon_type == 'universal':
            if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
                continue
            available_coupons.append(coupon)
            
        elif coupon.coupon_type == 'specific':
            assignment = CouponAssignment.query.filter_by(
                coupon_id=coupon.id, 
                user_id=user.id, 
                is_used=False
            ).first()
            if assignment:
                available_coupons.append(coupon)
                
    return render_template('user/user_coupon.html', user=user, coupons=available_coupons)


@user_bp.route('/earn/survey/<int:assignment_id>', methods=['GET', 'POST'])
@login_required
def survey_assignment(assignment_id):
    user = User.query.get(session['user_id'])
    assignment = SurveyAssignment.query.filter_by(id=assignment_id, user_id=user.id).first_or_404()
    survey = assignment.survey
    if request.method == 'POST':
        if survey.survey_type == 'call':
            decision = request.form.get('decision')
            assignment.status = 'waiting_for_call' if decision == 'accept' else 'declined'
            assignment.responded_at = datetime.now(timezone.utc)
            db.session.commit()
            flash('Survey response saved.', 'success')
            return redirect(url_for('user.dashboard'))
        for question in survey.questions:
            answer = request.form.get(f'question_{question.id}', '').strip()
            db.session.add(SurveyResponse(assignment_id=assignment.id, question_id=question.id, response_text=answer))
        assignment.status = 'completed'
        assignment.responded_at = datetime.now(timezone.utc)
        tx = _wallet_credit(user.id, survey.reward_amount, 'survey', 'survey_assignment', assignment.id, f'Survey reward: {survey.title}')
        if tx:
            assignment.reward_transaction_id = tx.id
            assignment.rewarded_at = datetime.now(timezone.utc)
        db.session.commit()
        flash('Survey submitted and reward added to your wallet.', 'success')
        return redirect(url_for('user.dashboard'))
    return render_template('user/survey_detail.html', user=user, assignment=assignment, survey=survey)


@user_bp.route('/validate-coupon', methods=['POST'])
@login_required
def validate_coupon_api():
    try:
        user_id = session.get('user_id')
        coupon_code = request.form.get('coupon_code')
        challenge_id = request.form.get('challenge_id')
        
        if not coupon_code:
            return jsonify({'success': False, 'error': 'Coupon code is required'})
            
        if not challenge_id:
            return jsonify({'success': False, 'error': 'Challenge ID is required'})
            
        challenge = ChallengeTemplate.query.get(challenge_id)
        if not challenge:
            return jsonify({'success': False, 'error': 'Challenge not found'})
            
        coupon = Coupon.query.filter_by(code=coupon_code.upper().strip(), is_deleted=False).first()
        if not coupon:
            return jsonify({'success': False, 'error': 'Invalid coupon code'})
            
        template_currency = (challenge.currency or 'INR').upper()
        coupon_currency = (coupon.currency or template_currency).upper()
        if coupon_currency != template_currency:
            return jsonify({'success': False, 'error': f'This coupon is in {coupon_currency}; the challenge is priced in {template_currency}.'})
        is_valid, msg, discount_amount, final_price = coupon.validate_for_user_and_price(user_id, float(challenge.price))
        
        if not is_valid:
            return jsonify({'success': False, 'error': msg})
            
        return jsonify({
            'success': True,
            'message': msg,
            'discount_amount': discount_amount,
            'final_price': final_price,
            'coupon_type': coupon.coupon_type,
            'discount_type': coupon.discount_type,
            'discount_value': coupon.discount_value
        })
        
    except Exception as e:
        print(f"Error validating coupon: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while validating the coupon'})

# ===== TRADING CALENDAR API =====
@user_bp.route('/api/calendar')
@login_required
def api_trading_calendar():
    try:
        user_id = session.get('user_id')
        month_str = request.args.get('month')  # format: 2026-06
        
        if month_str:
            try:
                year, month = int(month_str.split('-')[0]), int(month_str.split('-')[1])
            except:
                year, month = datetime.now(timezone.utc).year, datetime.now(timezone.utc).month
        else:
            year, month = datetime.now(timezone.utc).year, datetime.now(timezone.utc).month

        # Get all challenges for this user (all time, not just active)
        all_challenges = [
            c for c in ChallengePurchase.query.filter_by(user_id=user_id).all()
            if not _is_under_compliance_review(c)
        ]
        challenge_map = {c.id: c for c in all_challenges}

        if not all_challenges:
            return jsonify({'success': True, 'days': {}, 'summary': {}})

        challenge_ids = [c.id for c in all_challenges]

        # Date range for the month
        from calendar import monthrange
        _, days_in_month = monthrange(year, month)
        month_start = datetime(year, month, 1, tzinfo=timezone.utc)
        month_end = datetime(year, month, days_in_month, 23, 59, 59, tzinfo=timezone.utc)

        # Fetch all closed trades for this month across all challenges
        trades = TradeHistory.query.filter(
            TradeHistory.challenge_id.in_(challenge_ids),
            TradeHistory.is_open == False,
            TradeHistory.close_time >= month_start,
            TradeHistory.close_time <= month_end
        ).order_by(TradeHistory.close_time.asc()).all()

        # Group by date
        days = {}
        for t in trades:
            if not t.close_time:
                continue
            close_utc = t.close_time.replace(tzinfo=timezone.utc) if t.close_time.tzinfo is None else t.close_time
            day_key = close_utc.strftime('%Y-%m-%d')
            
            if day_key not in days:
                days[day_key] = {
                    'date': day_key,
                    'total_profit': 0.0,
                    'total_trades': 0,
                    'winning_trades': 0,
                    'losing_trades': 0,
                    'trades': []
                }
            
            profit = float(t.profit or 0)
            challenge = challenge_map.get(t.challenge_id)
            challenge_name = challenge.challenge_template.name if challenge and challenge.challenge_template else 'Challenge'
            
            days[day_key]['total_profit'] = round(days[day_key]['total_profit'] + profit, 2)
            days[day_key]['total_trades'] += 1
            if profit > 0:
                days[day_key]['winning_trades'] += 1
            elif profit < 0:
                days[day_key]['losing_trades'] += 1
            
            days[day_key]['trades'].append({
                'ticket': t.ticket,
                'symbol': t.symbol,
                'lots': t.lots,
                'profit': round(profit, 2),
                'open_time': t.open_time.isoformat() if t.open_time else None,
                'close_time': t.close_time.isoformat() if t.close_time else None,
                'challenge_name': challenge_name,
                'challenge_id': t.challenge_id
            })

        # Monthly summary
        all_trades_flat = [t for day in days.values() for t in day['trades']]
        total_profit = round(sum(t['profit'] for t in all_trades_flat), 2)
        total_trades = len(all_trades_flat)
        winning = sum(1 for t in all_trades_flat if t['profit'] > 0)
        win_rate = round(winning / total_trades * 100, 1) if total_trades > 0 else 0
        best_trade = max(all_trades_flat, key=lambda t: t['profit']) if all_trades_flat else None
        
        # Win streak
        sorted_trades = sorted(all_trades_flat, key=lambda t: t['close_time'] or '')
        streak = 0
        for t in reversed(sorted_trades):
            if t['profit'] > 0:
                streak += 1
            else:
                break

        # Most traded symbol
        from collections import Counter
        symbol_counts = Counter(t['symbol'] for t in all_trades_flat)
        top_symbol = symbol_counts.most_common(1)[0][0] if symbol_counts else None

        summary = {
            'total_profit': total_profit,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'win_streak': streak,
            'best_trade': best_trade,
            'top_symbol': top_symbol,
            'month': month_str or f'{year}-{month:02d}'
        }

        return jsonify({
            'success': True,
            'days': days,
            'summary': summary
        })

    except Exception as e:
        print(f"Calendar API error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
