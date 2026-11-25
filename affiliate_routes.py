from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from functools import wraps
from datetime import datetime, timezone
from models import db, User, CouponUsage, Affiliate, AffiliateApplication, AffiliatePayout, TradingJourney, ChallengeTemplate

affiliate_bp = Blueprint('affiliate', __name__, url_prefix='/affiliate')
PAYOUT_THRESHOLD = 10.0  # USD — minimum commission to request a payout


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def _affiliate_sales_rows(query):
    rows = []
    for usage in query.all():
        buyer = User.query.get(usage.user_id)
        purchase = TradingJourney.query.get(usage.challenge_purchase_id)
        challenge = ChallengeTemplate.query.get(purchase.challenge_template_id) if purchase else None
        rows.append({'usage': usage, 'buyer': buyer, 'challenge_name': challenge.name if challenge else 'Challenge'})
    return rows


def _current_user_affiliate():
    return Affiliate.query.filter_by(user_id=session['user_id']).first()


@affiliate_bp.route('/')
@login_required
def index():
    user_id = session['user_id']
    current_user = User.query.get(user_id)
    application = AffiliateApplication.query.filter_by(user_id=user_id).order_by(AffiliateApplication.created_at.desc()).first()
    affiliate = Affiliate.query.filter_by(user_id=user_id).first()
    if affiliate and not affiliate.is_active:
        return render_template('affiliate/paused.html', user=current_user)
    if affiliate:
        stats = affiliate.calculate_current_stats()
        unique_buyers = affiliate.get_unique_buyer_count()
        coupons = affiliate.get_coupons()
        sales = _affiliate_sales_rows(CouponUsage.query.filter(CouponUsage.coupon_id.in_(affiliate.get_coupon_ids())).order_by(CouponUsage.used_at.desc()).limit(10)) if affiliate.get_coupon_ids() else []
        return render_template('affiliate/dashboard.html', user=current_user, affiliate=affiliate, stats=stats, unique_buyers=unique_buyers, coupons=coupons, sales=sales, cycle=affiliate.get_current_cycle(), payout_threshold=PAYOUT_THRESHOLD)
    if application and application.status == 'pending':
        return render_template('affiliate/status.html', user=current_user, application=application)
    if application and application.status == 'rejected':
        return render_template('affiliate/status.html', user=current_user, application=application)
    return render_template('affiliate/apply.html', user=current_user)


@affiliate_bp.route('/apply', methods=['POST'])
@login_required
def apply():
    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip()
    if not full_name:
        flash('Full name is required', 'error'); return redirect(url_for('affiliate.index'))
    if sum(ch.isdigit() for ch in phone) < 10:
        flash('Phone number must contain at least 10 digits', 'error'); return redirect(url_for('affiliate.index'))
    if AffiliateApplication.query.filter_by(user_id=session['user_id'], status='pending').first():
        flash('You already have a pending application', 'error'); return redirect(url_for('affiliate.index'))
    if _current_user_affiliate():
        flash('You are already an affiliate', 'error'); return redirect(url_for('affiliate.index'))
    db.session.add(AffiliateApplication(user_id=session['user_id'], full_name=full_name, social_handle=request.form.get('social_handle', '').strip() or None, phone=phone, contact_email=request.form.get('contact_email', '').strip() or None, description=request.form.get('description', '').strip() or None, status='pending'))
    db.session.commit()
    flash('Application submitted. We will reply in 2-3 business days.', 'success')
    return redirect(url_for('affiliate.index'))


@affiliate_bp.route('/reapply', methods=['POST'])
@login_required
def reapply():
    application = AffiliateApplication.query.filter_by(user_id=session['user_id']).order_by(AffiliateApplication.created_at.desc()).first()
    if not application or application.status != 'rejected':
        flash('You can only re-apply after a rejected application.', 'error')
        return redirect(url_for('affiliate.index'))
    db.session.delete(application); db.session.commit()
    return redirect(url_for('affiliate.index'))


@affiliate_bp.route('/save-payout', methods=['POST'])
@login_required
def save_payout():
    affiliate = _current_user_affiliate()
    if not affiliate:
        flash('You are not an affiliate', 'error'); return redirect(url_for('affiliate.index'))
    method = request.form.get('payout_method', '').strip().lower()
    details = request.form.get('payout_details', '').strip()
    if method not in ('upi', 'usdt', 'bank'):
        flash('Choose a valid payout method', 'error')
    elif method == 'upi' and '@' not in details:
        flash('UPI details must contain @', 'error')
    elif method == 'usdt' and len(details) < 20:
        flash('USDT wallet address must be at least 20 characters', 'error')
    elif method == 'bank' and not details:
        flash('Bank details must not be empty', 'error')
    else:
        affiliate.payout_method, affiliate.payout_details = method, details
        db.session.commit(); flash('Payout details saved', 'success')
    return redirect(url_for('affiliate.index'))


@affiliate_bp.route('/request-payout', methods=['POST'])
@login_required
def request_payout():
    affiliate = _current_user_affiliate()
    if not affiliate:
        flash('You are not an affiliate', 'error'); return redirect(url_for('affiliate.index'))
    if not affiliate.is_active:
        flash('Your affiliate account is paused', 'error'); return redirect(url_for('affiliate.index'))
    cycle = affiliate.get_current_cycle()
    if not cycle:
        flash('No open payout cycle', 'error')
    elif not affiliate.payout_method or not affiliate.payout_details:
        flash('Save your payout details first (UPI ID / USDT wallet / bank account)', 'error')
    else:
        stats = affiliate.calculate_current_stats()
        if cycle.status == 'pending_request':
            flash('Payout already requested', 'error')
        elif stats['sales_count'] == 0:
            flash('No sales in this cycle yet', 'error')
        elif stats['total_commission'] < PAYOUT_THRESHOLD:
            flash(f"You need at least $10.00 commission to request a payout. Current: ${stats['total_commission']:.2f}", 'error')
        else:
            cycle.status = 'pending_request'; cycle.requested_at = datetime.now(timezone.utc)
            cycle.rejected_at = cycle.rejected_reason = cycle.rejected_by_id = None
            db.session.commit(); flash('Payout requested', 'success')
            return redirect(url_for('affiliate.index'))
    return redirect(url_for('affiliate.index'))


@affiliate_bp.route('/sales')
@login_required
def sales():
    affiliate = _current_user_affiliate()
    if not affiliate:
        flash('You are not an affiliate', 'error'); return redirect(url_for('affiliate.index'))
    coupon_ids = affiliate.get_coupon_ids()
    page = request.args.get('page', 1, type=int)
    query = CouponUsage.query.filter(CouponUsage.coupon_id.in_(coupon_ids)) if coupon_ids else CouponUsage.query.filter(False)
    pagination = query.order_by(CouponUsage.used_at.desc()).paginate(page=page, per_page=20, error_out=False)
    rows = _affiliate_sales_rows(pagination.items)
    return render_template('affiliate/sales.html', user=User.query.get(session['user_id']), sales=rows, pagination=pagination)


@affiliate_bp.route('/payouts')
@login_required
def payouts():
    affiliate = _current_user_affiliate()
    if not affiliate:
        flash('You are not an affiliate', 'error'); return redirect(url_for('affiliate.index'))
    cycles = AffiliatePayout.query.filter_by(affiliate_id=affiliate.id).order_by(AffiliatePayout.period_start.desc()).all()
    return render_template('affiliate/payouts.html', user=User.query.get(session['user_id']), cycles=cycles, current_stats=affiliate.calculate_current_stats())
