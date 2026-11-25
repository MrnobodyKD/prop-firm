from flask import render_template, request, redirect, url_for, flash, session, abort
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from models import db, User, Coupon, CouponUsage, Affiliate, AffiliateApplication, AffiliateCoupon, AffiliatePayout, TradingJourney, ChallengeTemplate
from . import admin_bp, admin_required


def _commission_value():
    raw = request.form.get('commission_percent', '').strip()
    try:
        value = 15.0 if not raw else float(raw)
        return value if 0 <= value <= 100 else None
    except (TypeError, ValueError):
        return None


def _coupon_from_form():
    code = request.form.get('coupon_code', '').upper().strip()
    if not code:
        return None, 'Coupon code is required'
    coupon = Coupon.query.filter_by(code=code, is_deleted=False).first()
    if not coupon:
        return None, 'Coupon not found'
    if coupon.coupon_type != 'influencer':
        return None, 'Coupon must be an influencer coupon. Create one in Coupons first.'
    if AffiliateCoupon.query.filter_by(coupon_id=coupon.id).first():
        return None, 'This coupon already belongs to another affiliate'
    return coupon, None


def _affiliate_sales_rows(items):
    rows = []
    for usage in items:
        buyer = User.query.get(usage.user_id)
        purchase = TradingJourney.query.get(usage.challenge_purchase_id)
        challenge = ChallengeTemplate.query.get(purchase.challenge_template_id) if purchase else None
        rows.append({'usage': usage, 'buyer': buyer, 'challenge_name': challenge.name if challenge else 'Challenge'})
    return rows


@admin_bp.route('/affiliates')
@admin_required
def admin_affiliates():
    applications = AffiliateApplication.query.filter_by(status='pending').order_by(AffiliateApplication.created_at.desc()).all()
    affiliates = Affiliate.query.order_by(Affiliate.created_at.desc()).all()
    for affiliate in affiliates:
        affiliate.current_stats = affiliate.calculate_current_stats()
    payout_requests = AffiliatePayout.query.filter_by(status='pending_request').order_by(AffiliatePayout.requested_at.desc()).all()
    return render_template('admin/affiliates.html', applications=applications, affiliates=affiliates, payout_requests=payout_requests,
                           application_count=len(applications), affiliate_count=len(affiliates), payout_request_count=len(payout_requests))


@admin_bp.route('/affiliates/<int:application_id>/approve', methods=['POST'])
@admin_required
def admin_affiliate_approve(application_id):
    application = AffiliateApplication.query.get(application_id)
    if not application or application.status != 'pending':
        flash('Pending application not found', 'error'); return redirect(url_for('admin.admin_affiliates'))
    commission = _commission_value()
    if commission is None:
        flash('Commission must be a number between 0 and 100', 'error'); return redirect(url_for('admin.admin_affiliates'))
    coupon, error = _coupon_from_form()
    if error:
        flash(error, 'error'); return redirect(url_for('admin.admin_affiliates'))
    if Affiliate.query.filter_by(user_id=application.user_id).first():
        flash('This user is already an affiliate', 'error'); return redirect(url_for('admin.admin_affiliates'))
    now = datetime.now(timezone.utc)
    affiliate = Affiliate(user_id=application.user_id, commission_percent=commission, is_active=True, source='applied', application_id=application.id, approved_by_id=session['user_id'], approved_at=now)
    db.session.add(affiliate)
    try:
        db.session.flush()
        db.session.add(AffiliateCoupon(affiliate_id=affiliate.id, coupon_id=coupon.id, added_by_id=session['user_id']))
        coupon.influencer_id = application.user_id
        application.status = 'approved'; application.reviewed_by_id = session['user_id']; application.reviewed_at = now
        db.session.add(AffiliatePayout(affiliate_id=affiliate.id, period_start=now, status='open'))
        db.session.commit()
    except IntegrityError:
        db.session.rollback(); flash('This coupon already belongs to another affiliate', 'error'); return redirect(url_for('admin.admin_affiliates'))
    flash('Affiliate approved', 'success'); return redirect(url_for('admin.admin_affiliates'))


@admin_bp.route('/affiliates/<int:application_id>/reject', methods=['POST'])
@admin_required
def admin_affiliate_reject(application_id):
    application = AffiliateApplication.query.get(application_id)
    reason = request.form.get('reason', '').strip()
    if not application or application.status != 'pending':
        flash('Pending application not found', 'error')
    elif not reason:
        flash('A rejection reason is required', 'error')
    else:
        application.status = 'rejected'; application.admin_notes = reason
        application.reviewed_by_id = session['user_id']; application.reviewed_at = datetime.now(timezone.utc)
        db.session.commit(); flash('Application rejected', 'success')
    return redirect(url_for('admin.admin_affiliates'))


@admin_bp.route('/affiliates/add', methods=['POST'])
@admin_required
def admin_affiliate_add():
    email = request.form.get('email', '').strip()
    user = User.query.filter(db.func.lower(User.email) == email.lower()).first()
    if not user:
        flash('User not found. The user must have an account first.', 'error'); return redirect(url_for('admin.admin_affiliates'))
    if Affiliate.query.filter_by(user_id=user.id).first():
        flash('This user is already an affiliate', 'error'); return redirect(url_for('admin.admin_affiliates'))
    commission = _commission_value()
    if commission is None:
        flash('Commission must be a number between 0 and 100', 'error'); return redirect(url_for('admin.admin_affiliates'))
    coupon, error = _coupon_from_form()
    if error:
        flash(error, 'error'); return redirect(url_for('admin.admin_affiliates'))
    now = datetime.now(timezone.utc)
    affiliate = Affiliate(user_id=user.id, commission_percent=commission, source='direct', approved_by_id=session['user_id'], approved_at=now)
    db.session.add(affiliate)
    try:
        db.session.flush(); db.session.add(AffiliateCoupon(affiliate_id=affiliate.id, coupon_id=coupon.id, added_by_id=session['user_id']))
        coupon.influencer_id = user.id
        db.session.add(AffiliatePayout(affiliate_id=affiliate.id, period_start=now, status='open'))
        db.session.commit()
    except IntegrityError:
        db.session.rollback(); flash('This coupon already belongs to another affiliate', 'error'); return redirect(url_for('admin.admin_affiliates'))
    flash('Affiliate added', 'success'); return redirect(url_for('admin.admin_affiliates'))


@admin_bp.route('/affiliates/<int:affiliate_id>')
@admin_required
def admin_affiliate_detail(affiliate_id):
    affiliate = Affiliate.query.get_or_404(affiliate_id)
    stats = affiliate.calculate_current_stats(); unique_buyers = affiliate.get_unique_buyer_count()
    coupons = affiliate.get_coupons(); coupon_ids = affiliate.get_coupon_ids()
    page = request.args.get('page', 1, type=int)
    query = CouponUsage.query.filter(CouponUsage.coupon_id.in_(coupon_ids)) if coupon_ids else CouponUsage.query.filter(False)
    pagination = query.order_by(CouponUsage.used_at.desc()).paginate(page=page, per_page=20, error_out=False)
    sales = _affiliate_sales_rows(pagination.items)
    payouts = AffiliatePayout.query.filter_by(affiliate_id=affiliate.id).order_by(AffiliatePayout.period_start.desc()).all()
    return render_template('admin/affiliate_detail.html', affiliate=affiliate, stats=stats, unique_buyers=unique_buyers, coupons=coupons, sales=sales, pagination=pagination, payouts=payouts)


@admin_bp.route('/affiliates/<int:affiliate_id>/toggle', methods=['POST'])
@admin_required
def admin_affiliate_toggle(affiliate_id):
    affiliate = Affiliate.query.get_or_404(affiliate_id); affiliate.is_active = not affiliate.is_active
    db.session.commit(); flash('Affiliate resumed' if affiliate.is_active else 'Affiliate paused', 'success')
    return redirect(url_for('admin.admin_affiliate_detail', affiliate_id=affiliate.id))


@admin_bp.route('/affiliates/<int:affiliate_id>/add-coupon', methods=['POST'])
@admin_required
def admin_affiliate_add_coupon(affiliate_id):
    affiliate = Affiliate.query.get_or_404(affiliate_id); coupon, error = _coupon_from_form()
    if error:
        flash(error, 'error')
    else:
        db.session.add(AffiliateCoupon(affiliate_id=affiliate.id, coupon_id=coupon.id, added_by_id=session['user_id']))
        coupon.influencer_id = affiliate.user_id
        try:
            db.session.commit(); flash('Coupon linked to affiliate', 'success')
        except IntegrityError:
            db.session.rollback(); flash('This coupon already belongs to another affiliate', 'error')
    return redirect(url_for('admin.admin_affiliate_detail', affiliate_id=affiliate_id))


@admin_bp.route('/affiliates/<int:affiliate_id>/remove-coupon', methods=['POST'])
@admin_required
def admin_affiliate_remove_coupon(affiliate_id):
    affiliate = Affiliate.query.get_or_404(affiliate_id)
    try:
        coupon_id = int(request.form.get('coupon_id', ''))
    except ValueError:
        coupon_id = 0
    link = AffiliateCoupon.query.filter_by(affiliate_id=affiliate.id, coupon_id=coupon_id).first()
    if link:
        coupon = Coupon.query.get(coupon_id); db.session.delete(link)
        if coupon:
            coupon.influencer_id = None
        db.session.commit(); flash('Coupon removed from affiliate', 'success')
    else:
        flash('Affiliate coupon link not found', 'error')
    return redirect(url_for('admin.admin_affiliate_detail', affiliate_id=affiliate_id))


@admin_bp.route('/affiliates/<int:affiliate_id>/set-commission', methods=['POST'])
@admin_required
def admin_affiliate_set_commission(affiliate_id):
    affiliate = Affiliate.query.get_or_404(affiliate_id); commission = _commission_value()
    if commission is None:
        flash('Commission must be a number between 0 and 100', 'error')
    else:
        affiliate.commission_percent = commission; db.session.commit(); flash('Commission updated', 'success')
    return redirect(url_for('admin.admin_affiliate_detail', affiliate_id=affiliate_id))


@admin_bp.route('/affiliates/payouts/<int:payout_id>/mark-paid', methods=['POST'])
@admin_required
def admin_affiliate_payout_paid(payout_id):
    cycle = AffiliatePayout.query.get(payout_id); reference = request.form.get('payment_reference', '').strip()
    if not cycle or cycle.status != 'pending_request':
        flash('Payout request not found or already processed', 'error'); return redirect(url_for('admin.admin_affiliates'))
    if not reference:
        flash('Payment reference is required', 'error'); return redirect(url_for('admin.admin_affiliates'))
    affiliate = Affiliate.query.get(cycle.affiliate_id); stats = affiliate.calculate_current_stats(); now = datetime.now(timezone.utc)
    cycle.total_sales = stats['total_sales']; cycle.total_commission = stats['total_commission']
    cycle.period_end = now; cycle.status = 'paid'; cycle.paid_at = now; cycle.paid_by_id = session['user_id']
    cycle.payment_reference = reference; cycle.admin_notes = request.form.get('admin_notes', '').strip() or None
    db.session.add(AffiliatePayout(affiliate_id=affiliate.id, period_start=now, status='open'))
    db.session.commit(); flash('Payout marked paid', 'success'); return redirect(url_for('admin.admin_affiliates'))


@admin_bp.route('/affiliates/payouts/<int:payout_id>/reject', methods=['POST'])
@admin_required
def admin_affiliate_payout_reject(payout_id):
    cycle = AffiliatePayout.query.get(payout_id); reason = request.form.get('reason', '').strip()
    if not cycle or cycle.status != 'pending_request':
        flash('Payout request not found or already processed', 'error')
    elif not reason:
        flash('A rejection reason is required', 'error')
    else:
        cycle.status = 'open'; cycle.rejected_at = datetime.now(timezone.utc); cycle.rejected_reason = reason; cycle.rejected_by_id = session['user_id']
        db.session.commit(); flash('Payout request rejected; sales will continue accumulating', 'success')
    return redirect(url_for('admin.admin_affiliates'))
