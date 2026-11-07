from flask import current_app, render_template, request, redirect, url_for, flash, session, jsonify, abort, Response, send_file, send_from_directory
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, extract, and_, or_
from models import db, User, ChallengeTemplate, ChallengePurchase, Payout, PayoutAuditLog, FAQ, SupportTicket, TicketMessage, Payment, PaymentMethod, AdminLog, Notification, UserNotification, NotificationTemplate, Coupon, CouponUsage, CouponAssignment, ProgressionRequest, RulebookSection, RuleLog
from . import admin_bp, admin_required
from notification_service import create_notification, notify_all_users
import secrets
import csv
import io
import json
import os
import uuid
from werkzeug.utils import secure_filename

from . import _admin_name, _notify_user, _notify_challenge_passed, _notify_challenge_breached, _activate_progression_stage, _payout_audit, _eligible_funded_count, _payout_stats

PAYMENT_IMAGE_MAX_BYTES = 5 * 1024 * 1024
PAYMENT_IMAGE_SIGNATURES = {
    'png': b'\x89PNG\r\n\x1a\n',
    'jpg': b'\xff\xd8\xff',
    'gif': b'GIF8',
    'webp': b'RIFF',
}


def _save_payment_method_image(upload):
    if not upload or not upload.filename:
        return None
    data = upload.read(PAYMENT_IMAGE_MAX_BYTES + 1)
    upload.stream.seek(0)
    if len(data) > PAYMENT_IMAGE_MAX_BYTES:
        raise ValueError('Image must be 5 MB or smaller.')
    extension = secure_filename(upload.filename).rsplit('.', 1)[-1].lower() if '.' in upload.filename else ''
    signature = next((ext for ext, header in PAYMENT_IMAGE_SIGNATURES.items()
                      if data.startswith(header) and (ext != 'webp' or data[8:12] == b'WEBP')),
                     None)
    normalized_extension = 'jpg' if extension == 'jpeg' else extension
    if signature is None or signature != normalized_extension:
        raise ValueError('Upload a valid PNG, JPEG, GIF, or WebP image.')
    filename = f'{uuid.uuid4().hex}.{signature}'
    directory = os.path.join(current_app.instance_path, 'payment_method_assets')
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, filename), 'wb') as image_file:
        image_file.write(data)
    return filename


def _delete_payment_method_image(filename):
    if filename and os.path.basename(filename) == filename:
        path = os.path.join(current_app.instance_path, 'payment_method_assets', filename)
        if os.path.isfile(path):
            os.remove(path)


def _save_method_form(method=None):
    name = request.form.get('name', '').strip()
    method_type = request.form.get('type', '').strip()
    currency = request.form.get('currency', '').strip().upper()
    details_text = request.form.get('details', '').strip()
    if not name or not method_type or not currency:
        flash('Name, type, and currency are required.', 'error')
        return False
    try:
        details = json.loads(details_text) if details_text else {}
        if not isinstance(details, dict):
            raise ValueError('Details must be a JSON object.')
        rate_text = request.form.get('exchange_rate_to_usd', '').strip()
        rate = float(rate_text) if rate_text else None
        if rate is not None and rate <= 0:
            raise ValueError('Exchange rate must be greater than zero.')
        sort_order = int(request.form.get('sort_order', 0))
        uploaded = {}
        for field in ('qr_image', 'help_image'):
            if field in request.files and request.files[field].filename:
                uploaded[field] = _save_payment_method_image(request.files[field])
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        flash(str(exc), 'error')
        return False

    if method is None:
        method = PaymentMethod()
        db.session.add(method)
    old_images = []
    for field, filename in uploaded.items():
        old_name = getattr(method, field)
        if old_name:
            old_images.append(old_name)
        setattr(method, field, filename)
    for field in ('qr_image', 'help_image'):
        if request.form.get(f'remove_{field}') == 'on':
            old_name = getattr(method, field)
            if old_name:
                old_images.append(old_name)
            setattr(method, field, None)
    method.name = name
    method.type = method_type
    method.currency = currency
    method.details = details
    method.instructions = request.form.get('instructions', '').strip()
    method.exchange_rate_to_usd = rate
    method.sort_order = sort_order
    method.is_active = request.form.get('is_active') == 'on'
    db.session.commit()
    for old_name in old_images:
        _delete_payment_method_image(old_name)
    flash('Payment method saved.', 'success')
    return True


@admin_bp.route('/payment-methods')
@admin_required
def admin_payment_methods():
    methods = PaymentMethod.query.order_by(PaymentMethod.sort_order, PaymentMethod.name).all()
    edit_id = request.args.get('edit', type=int)
    edit_method = PaymentMethod.query.get(edit_id) if edit_id else None
    return render_template('admin/payment_methods.html', methods=methods, edit_method=edit_method)


@admin_bp.route('/payment-methods/new', methods=['POST'])
@admin_required
def admin_payment_method_create():
    if _save_method_form():
        return redirect(url_for('admin.admin_payment_methods'))
    return redirect(url_for('admin.admin_payment_methods'))


@admin_bp.route('/payment-methods/<int:method_id>/edit', methods=['POST'])
@admin_required
def admin_payment_method_edit(method_id):
    method = PaymentMethod.query.get_or_404(method_id)
    _save_method_form(method)
    return redirect(url_for('admin.admin_payment_methods', edit=method.id))


@admin_bp.route('/payment-methods/<int:method_id>/toggle', methods=['POST'])
@admin_required
def admin_payment_method_toggle(method_id):
    method = PaymentMethod.query.get_or_404(method_id)
    method.is_active = not method.is_active
    db.session.commit()
    flash('Payment method updated.', 'success')
    return redirect(url_for('admin.admin_payment_methods'))


@admin_bp.route('/payment-methods/<int:method_id>/delete', methods=['POST'])
@admin_required
def admin_payment_method_delete(method_id):
    method = PaymentMethod.query.get_or_404(method_id)
    if Payment.query.filter_by(payment_method_id=method.id).first():
        flash('This payment method has payment history and cannot be deleted.', 'error')
        return redirect(url_for('admin.admin_payment_methods'))
    _delete_payment_method_image(method.qr_image)
    _delete_payment_method_image(method.help_image)
    db.session.delete(method)
    db.session.commit()
    flash('Payment method deleted.', 'success')
    return redirect(url_for('admin.admin_payment_methods'))


@admin_bp.route('/manual-claims')
@admin_required
def admin_manual_claims():
    claims = Payment.query.filter(
        Payment.payment_method_type == 'manual',
        Payment.status.in_(['pending', 'paid', 'rejected'])
    ).order_by(Payment.status != 'pending', Payment.created_at.desc()).all()
    partial_crypto = Payment.query.filter_by(payment_method_type='nowpayments', status='pending', gateway_status='partially_paid').order_by(Payment.created_at.desc()).all()
    return render_template('admin/manual_claims.html', claims=claims, partial_crypto=partial_crypto)


def record_paid_coupon_usage(payment):
    if not payment.coupon_id:
        return
    coupon = Coupon.query.with_for_update().get(payment.coupon_id)
    if not coupon or CouponUsage.query.filter_by(coupon_id=coupon.id, user_id=payment.user_id).first():
        return
    coupon.used_count = (coupon.used_count or 0) + 1
    if coupon.coupon_type == 'specific':
        assignment = CouponAssignment.query.filter_by(coupon_id=coupon.id, user_id=payment.user_id, is_used=False).first()
        if assignment:
            assignment.is_used = True
    original_price = float(payment.challenge_template.price) if payment.challenge_template else float(payment.amount)
    db.session.add(CouponUsage(
        coupon_id=coupon.id,
        user_id=payment.user_id,
        challenge_purchase_id=payment.challenge_purchase_id,
        original_price=original_price,
        discount_amount=max(0.0, original_price - float(payment.amount or 0)),
        final_price=float(payment.amount or 0),
        used_at=datetime.now(timezone.utc),
    ))


@admin_bp.route('/manual-claims/<int:payment_id>/<action>', methods=['POST'])
@admin_required
def admin_manual_claim_action(payment_id, action):
    payment = Payment.query.with_for_update().get_or_404(payment_id)
    if payment.payment_method_type != 'manual' or payment.status != 'pending':
        flash('Only pending manual claims can be reviewed.', 'error')
        return redirect(url_for('admin.admin_manual_claims'))
    if action == 'approve':
        from app import provision_challenge
        user = User.query.get_or_404(payment.user_id)
        success, result = provision_challenge(payment, user, payment.challenge_template_id)
        if not success:
            db.session.rollback()
            flash(f'Challenge provisioning failed: {result}', 'error')
            return redirect(url_for('admin.admin_manual_claims'))
        payment.status = 'paid'
        payment.paid_amount = payment.amount
        payment.gateway_status = 'manual_approved'
        record_paid_coupon_usage(payment)
        _notify_user(payment.user_id, 'Payment Approved', 'Your payment was verified and your challenge is now available.')
    elif action == 'reject':
        payment.status = 'rejected'
        payment.gateway_status = 'manual_rejected'
        payment.gateway_message = request.form.get('reason', '').strip()
        _notify_user(payment.user_id, 'Payment Not Approved', 'Your payment proof could not be approved. You may submit a new payment claim.')
    else:
        abort(404)
    db.session.commit()
    flash('Manual payment claim updated.', 'success')
    return redirect(url_for('admin.admin_manual_claims'))


@admin_bp.route('/payment-evidence/<int:payment_id>')
@admin_required
def admin_payment_evidence(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if not payment.evidence_path or os.path.basename(payment.evidence_path) != payment.evidence_path:
        abort(404)
    return send_from_directory(os.path.join(current_app.instance_path, 'payment_evidence'), payment.evidence_path)

@admin_bp.route('/payments')
@admin_required
def admin_payments():
    return render_template('admin/payments.html')


@admin_bp.route('/payments/<int:payment_id>')
@admin_required
def admin_payment_detail(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    return render_template('admin/payment_detail.html', payment=payment)


@admin_bp.route('/api/payments/analytics', methods=['POST'])
@admin_required
def admin_api_payments_analytics():
    data = request.get_json() or {}
    search = data.get('search', '').strip()
    status = data.get('status', 'all')
    payment_type = data.get('payment_type', 'all')
    page = max(1, int(data.get('page', 1)))
    per_page = min(100, int(data.get('per_page', 50)))
    
    date_from = data.get('date_from')
    date_to = data.get('date_to')
    
    query = Payment.query.join(User, Payment.user_id == User.id)
    
    if search:
        query = query.filter(
            (User.first_name.ilike(f'%{search}%')) |
            (User.last_name.ilike(f'%{search}%')) |
            (User.email.ilike(f'%{search}%')) |
            (Payment.payment_id.ilike(f'%{search}%'))
        )
    
    if status == 'success':
        query = query.filter(Payment.status.in_(['SUCCESS', 'success', 'paid']))
    elif status == 'pending':
        query = query.filter(Payment.status.in_(['pending', 'waiting']))
    elif status != 'all':
        query = query.filter(Payment.status.ilike(status))
    if payment_type == 'manual':
        query = query.filter(Payment.payment_method_type == 'manual')
    elif payment_type == 'crypto':
        query = query.filter(Payment.payment_method_type == 'nowpayments')
    elif payment_type == 'cashfree':
        query = query.filter(or_(Payment.payment_method_type == 'cashfree', Payment.payment_method_type.is_(None), Payment.gateway == 'cashfree'))
    elif payment_type == 'pending':
        query = query.filter(or_(Payment.status.in_(['pending', 'waiting']), Payment.gateway_status == 'partially_paid'))
    
    if date_from and date_from != 'null' and date_from != 'undefined':
        try:
            query = query.filter(Payment.created_at >= datetime.fromisoformat(date_from.replace('Z', '+00:00')))
        except:
            pass
    if date_to and date_to != 'null' and date_to != 'undefined':
        try:
            query = query.filter(Payment.created_at <= datetime.fromisoformat(date_to.replace('Z', '+00:00')))
        except:
            pass
    
    # Stats
    success_ids = [p.id for p in query.filter(Payment.status.in_(['SUCCESS', 'success', 'paid'])).all()]
    total_revenue = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.id.in_(success_ids)
    ).scalar() or 0 if success_ids else 0
    
    total_successful = query.filter(Payment.status.in_(['SUCCESS', 'success', 'paid'])).count()
    total_pending = query.filter(Payment.status.in_(['pending', 'waiting'])).count()
    total_failed = query.filter(Payment.status.ilike('failed')).count()
    total_all = query.count()
    
    stats = {
        'total_revenue': float(total_revenue),
        'successful': total_successful,
        'pending': total_pending,
        'failed': total_failed,
        'unique_buyers': query.distinct(Payment.user_id).count(),
        'repeat_buyers': db.session.query(func.count('*')).select_from(
            db.session.query(Payment.user_id, func.count(Payment.id).label('cnt'))
            .filter(Payment.id.in_([p.id for p in query.all()]))
            .group_by(Payment.user_id).having(func.count(Payment.id) > 1).subquery()
        ).scalar() or 0,
        'avg_order_value': round(float(total_revenue) / max(total_successful, 1), 2),
        'success_rate': round((total_successful / max(total_all, 1)) * 100, 1)
    }
    
    # Revenue trend (last 30 days or custom range)
    trend_start = datetime.now(timezone.utc) - timedelta(days=30)
    if date_from:
        try: trend_start = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
        except: pass
    
    trend = db.session.query(
        func.date(Payment.created_at).label('date'),
        func.coalesce(func.sum(Payment.amount), 0).label('total')
    ).filter(
        Payment.status.in_(['SUCCESS', 'success', 'paid']),
        Payment.created_at >= trend_start
    ).group_by(func.date(Payment.created_at)).order_by('date').all()
    
    revenue_trend = {
        'labels': [str(t.date) for t in trend],
        'values': [float(t.total) for t in trend]
    }
    
    # Top spenders (all time)
    top_spenders = db.session.query(
        User.first_name, User.last_name, User.email,
        func.count(Payment.id).label('order_count'),
        func.coalesce(func.sum(Payment.amount), 0).label('total_spent'),
        func.max(Payment.created_at).label('last_purchase')
    ).join(Payment, Payment.user_id == User.id)\
     .filter(Payment.status.in_(['SUCCESS', 'success', 'paid']))\
     .group_by(User.id)\
     .order_by(func.sum(Payment.amount).desc())\
     .limit(10).all()
    
    top_spenders_data = [{
        'name': f"{s.first_name} {s.last_name}",
        'email': s.email,
        'order_count': s.order_count,
        'total_spent': float(s.total_spent),
        'last_purchase': s.last_purchase.strftime('%d %b %Y') if s.last_purchase else '--'
    } for s in top_spenders]
    
    # Challenge performance
    challenge_perf = db.session.query(
        ChallengeTemplate.name,
        ChallengeTemplate.id,
        func.count(Payment.id).label('sales'),
        func.coalesce(func.sum(Payment.amount), 0).label('revenue')
    ).join(Payment, Payment.challenge_template_id == ChallengeTemplate.id)\
     .group_by(ChallengeTemplate.id)\
     .order_by(func.sum(Payment.amount).desc())\
     .limit(10).all()
    
    challenge_perf_data = []
    for c in challenge_perf:
        conv_success = Payment.query.filter(
            Payment.status.in_(['SUCCESS', 'success', 'paid']),
            Payment.challenge_template_id == c.id
        ).count()
        challenge_perf_data.append({
            'name': c.name,
            'sales': c.sales,
            'revenue': float(c.revenue),
            'conversion': round((conv_success / max(c.sales, 1)) * 100, 1)
        })
    
    # Payments list
    pagination = query.order_by(Payment.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    payments_data = []
    for p in pagination.items:
        coupon_code = None
        coupon_discount = 0
        if p.coupon_id:
            coupon = Coupon.query.get(p.coupon_id)
            if coupon:
                coupon_code = coupon.code
                coupon_discount = round(float(p.expected_amount or 0) - float(p.amount or 0), 2)
        
        challenge_name = '--'
        challenge_price = 0
        if p.challenge_purchase and p.challenge_purchase.challenge_template:
            challenge_name = p.challenge_purchase.challenge_template.name
            challenge_price = float(p.challenge_purchase.challenge_template.price)
        elif p.challenge_template:
            challenge_name = p.challenge_template.name
            challenge_price = float(p.challenge_template.price)
        
        payments_data.append({
            'id': p.id,
            'order_id': p.payment_id,
            'user_name': p.user.get_full_name() if p.user else '--',
            'user_email': p.user.email if p.user else '',
            'challenge_name': challenge_name,
            'challenge_price': challenge_price,
            'final_amount': float(p.amount or 0),
            'currency': p.currency or 'USD',
            'local_amount': float(p.amount_local) if p.amount_local is not None else None,
            'local_currency': p.local_currency,
            'method': p.method_name or p.payment_method or p.gateway or 'Payment',
            'reference': p.external_reference or p.gateway_id or p.payment_id,
            'detail_url': url_for('admin.admin_payment_detail', payment_id=p.id),
            'coupon_code': coupon_code,
            'coupon_discount': coupon_discount,
            'status': p.status,
            'date': p.created_at.strftime('%d %b %Y, %I:%M %p') if p.created_at else '--'
        })
    
    return jsonify({
        'success': True,
        'stats': stats,
        'revenue_trend': revenue_trend,
        'top_spenders': top_spenders_data,
        'challenge_performance': challenge_perf_data,
        'payments': payments_data,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@admin_bp.route('/api/payments/analytics/export')
@admin_required
def admin_api_payments_export():
    search = request.args.get('search', '').strip()
    status = request.args.get('status', 'all')
    payment_type = request.args.get('payment_type', 'all')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = Payment.query.join(User, Payment.user_id == User.id)
    
    if search:
        query = query.filter(
            (User.first_name.ilike(f'%{search}%')) |
            (User.last_name.ilike(f'%{search}%')) |
            (User.email.ilike(f'%{search}%')) |
            (Payment.payment_id.ilike(f'%{search}%'))
        )
    
    if status == 'success':
        query = query.filter(Payment.status.in_(['SUCCESS', 'success', 'paid']))
    elif status == 'pending':
        query = query.filter(Payment.status.in_(['pending', 'waiting']))
    elif status != 'all':
        query = query.filter(Payment.status.ilike(status))
    if payment_type == 'manual':
        query = query.filter(Payment.payment_method_type == 'manual')
    elif payment_type == 'crypto':
        query = query.filter(Payment.payment_method_type == 'nowpayments')
    elif payment_type == 'cashfree':
        query = query.filter(or_(Payment.payment_method_type == 'cashfree', Payment.payment_method_type.is_(None), Payment.gateway == 'cashfree'))
    elif payment_type == 'pending':
        query = query.filter(or_(Payment.status.in_(['pending', 'waiting']), Payment.gateway_status == 'partially_paid'))
    
    if date_from and date_from != 'null' and date_from != 'undefined' and date_from != '':
        try:
            query = query.filter(Payment.created_at >= datetime.fromisoformat(date_from.replace('Z', '+00:00')))
        except:
            pass
    if date_to and date_to != 'null' and date_to != 'undefined' and date_to != '':
        try:
            query = query.filter(Payment.created_at <= datetime.fromisoformat(date_to.replace('Z', '+00:00')))
        except:
            pass
    
    payments = query.order_by(Payment.created_at.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Order ID', 'User Name', 'User Email', 'Challenge', 'Challenge Price', 'Final Amount', 'Coupon Code', 'Coupon Discount', 'Status', 'Date'])
    
    for p in payments:
        coupon_code = ''
        coupon_discount = 0
        if p.coupon_id:
            coupon = Coupon.query.get(p.coupon_id)
            if coupon:
                coupon_code = coupon.code
                coupon_discount = round(float(p.expected_amount or 0) - float(p.amount or 0), 2)
        
        challenge_name = ''
        challenge_price = 0
        if p.challenge_purchase and p.challenge_purchase.challenge_template:
            challenge_name = p.challenge_purchase.challenge_template.name
            challenge_price = float(p.challenge_purchase.challenge_template.price)
        elif p.challenge_template:
            challenge_name = p.challenge_template.name
            challenge_price = float(p.challenge_template.price)
        
        writer.writerow([
            p.payment_id,
            p.user.get_full_name() if p.user else '',
            p.user.email if p.user else '',
            challenge_name,
            challenge_price,
            float(p.amount or 0),
            coupon_code,
            coupon_discount,
            p.status,
            p.created_at.strftime('%Y-%m-%d %H:%M:%S') if p.created_at else ''
        ])
    
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=payment_analytics.csv'})


@admin_bp.route('/payment/<int:payment_id>/mark-refund', methods=['POST'])
@admin_required
def admin_mark_refund(payment_id):
    from models import AdminAuditLog
    payment = Payment.query.get_or_404(payment_id)
    
    if payment.status.lower() != 'success':
        return jsonify({'success': False, 'message': 'Cannot refund failed payment.'})
        
    audit = AdminAuditLog(
        admin_id=session.get('user_id'),
        action='marked_refund_eligible',
        payment_id=payment.id,
        old_value='False',
        new_value='True',
        ip_address=request.remote_addr
    )
    db.session.add(audit)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Payment marked as refund eligible.'})


@admin_bp.route('/payments/<int:payment_id>/refund', methods=['POST'])
@admin_required
def refund_payment(payment_id):
    return jsonify({'success': False, 'message': 'Payment must be marked eligible first.'})


@admin_bp.route('/payments/<int:payment_id>/update-status', methods=['POST'])
@admin_required
def update_payment_status(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    new_status = request.form.get('status')
    
    if new_status in ['pending', 'success', 'failed', 'refunded']:
        payment.status = new_status
        db.session.commit()
        flash(f'Payment status updated to {new_status}.', 'success')
    else:
        flash('Invalid status.', 'error')
    
    return redirect(url_for('admin.admin_payments'))


@admin_bp.route('/payouts')
@admin_required
def admin_payouts():
    payouts = Payout.query.order_by(Payout.created_at.desc()).all()
    stats = _payout_stats(Payout.query)
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    paid_payouts = [p for p in payouts if p.status == 'paid']
    approved_payouts = [p for p in payouts if p.status in ['approved', 'paid']]
    rejected_payouts = [p for p in payouts if p.status == 'rejected']
    analytics = {
        'week_paid': sum(p.amount or 0 for p in paid_payouts if p.paid_at and (p.paid_at.replace(tzinfo=timezone.utc) if p.paid_at.tzinfo is None else p.paid_at) >= week_start),
        'month_paid': sum(p.amount or 0 for p in paid_payouts if p.paid_at and (p.paid_at.replace(tzinfo=timezone.utc) if p.paid_at.tzinfo is None else p.paid_at) >= month_start),
        'all_paid': sum(p.amount or 0 for p in paid_payouts),
        'approved_amount': sum(p.amount or 0 for p in approved_payouts),
        'paid_amount': sum(p.amount or 0 for p in paid_payouts),
        'rejected_amount': sum(p.amount or 0 for p in rejected_payouts),
        'average_size': stats['average'],
        'pending_liability': stats['total_pending'],
        'top_traders': db.session.query(User.first_name, User.last_name, func.count(Payout.id).label('count'), func.coalesce(func.sum(Payout.amount), 0).label('amount'))
            .join(Payout, Payout.user_id == User.id)
            .group_by(User.id)
            .order_by(func.count(Payout.id).desc())
            .limit(5).all()
    }
    return render_template('admin/payouts.html', payouts=payouts, stats=stats, analytics=analytics)


@admin_bp.route('/payouts/history')
@admin_required
def admin_payout_history():
    query = Payout.query.join(User, Payout.user_id == User.id).join(ChallengePurchase, Payout.challenge_purchase_id == ChallengePurchase.id)
    username = request.args.get('username', '').strip()
    challenge = request.args.get('challenge', '').strip()
    status = request.args.get('status', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    amount_min = request.args.get('amount_min', '').strip()
    amount_max = request.args.get('amount_max', '').strip()

    if username:
        query = query.filter(or_(User.first_name.ilike(f'%{username}%'), User.last_name.ilike(f'%{username}%'), User.email.ilike(f'%{username}%'), Payout.username_snapshot.ilike(f'%{username}%')))
    if challenge:
        query = query.filter(Payout.challenge_name_snapshot.ilike(f'%{challenge}%'))
    if status:
        query = query.filter(Payout.status == status)
    if date_from:
        query = query.filter(Payout.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Payout.created_at < datetime.fromisoformat(date_to) + timedelta(days=1))
    if amount_min:
        query = query.filter(Payout.amount >= float(amount_min))
    if amount_max:
        query = query.filter(Payout.amount <= float(amount_max))

    payouts = query.order_by(Payout.created_at.desc()).all()
    return render_template('admin/payout_history.html', payouts=payouts, stats=_payout_stats(query))


@admin_bp.route('/payouts/export')
@admin_required
def export_payouts():
    payouts = Payout.query.order_by(Payout.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Request Date', 'Username', 'Challenge', 'Account Size', 'Account Type', 'Requested Amount', 'Status', 'Payment Method', 'Approval Date', 'Payment Date', 'Transaction Reference', 'Rejection Reason'])
    for payout in payouts:
        writer.writerow([
            payout.created_at.strftime('%Y-%m-%d %H:%M') if payout.created_at else '',
            payout.username_snapshot or (payout.user.get_full_name() if payout.user else ''),
            payout.challenge_name_snapshot,
            payout.account_size_snapshot,
            payout.account_type_snapshot,
            payout.amount,
            payout.status,
            payout.payment_method,
            payout.approved_at.strftime('%Y-%m-%d %H:%M') if payout.approved_at else '',
            payout.paid_at.strftime('%Y-%m-%d %H:%M') if payout.paid_at else '',
            payout.transaction_id or '',
            payout.rejection_reason or ''
        ])
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=payouts.csv'})


@admin_bp.route('/payouts/<int:payout_id>/<action>', methods=['POST'])
@admin_required
def admin_payout_action(payout_id, action):
    payout = Payout.query.get_or_404(payout_id)
    admin_user = User.query.get(session['user_id'])
    now = datetime.now(timezone.utc)

    if action == 'review':
        if payout.status != 'pending':
            flash('Only pending requests can be moved to review.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        payout.status = 'under_review'
        payout.reviewed_at = now
        _payout_audit(payout, 'under_review', admin_user, 'Moved to review.')
        _notify_user(payout.user_id, 'Payout under review', f'Your ${payout.amount:.2f} payout request is now under review.', admin_user.id)
    elif action == 'approve':
        if payout.status not in ['pending', 'under_review']:
            flash('Only pending or under review requests can be approved.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        expected = request.form.get('expected_payment_time', '').strip()
        if not expected:
            flash('Expected payment time is required.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        payout.status = 'approved'
        payout.approved_at = now
        payout.expected_payment_time = expected
        _payout_audit(payout, 'approved', admin_user, f'Expected payment: {expected}')
        create_notification(
            payout.user_id,
            'Payout Approved',
            'Your payout request has been approved and will be processed shortly.',
            'payout',
            action_url='/user/payouts',
            icon='dollar',
            admin_id=admin_user.id,
            dedupe_key=f'payout-approved:{payout.id}',
        )
    elif action == 'reject':
        reason = request.form.get('rejection_reason', '').strip()
        if not reason:
            flash('Rejection reason is required.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        payout.status = 'rejected'
        payout.rejection_reason = reason
        payout.reviewed_at = now
        _payout_audit(payout, 'rejected', admin_user, reason)
        create_notification(
            payout.user_id,
            'Payout Request Declined',
            'Your payout request could not be approved. Please review the reason provided and submit a new request if necessary.',
            'payout',
            action_url='/user/payouts',
            icon='warning',
            admin_id=admin_user.id,
            dedupe_key=f'payout-rejected:{payout.id}',
        )
    elif action == 'paid':
        if payout.status != 'approved':
            flash('Only approved requests can be marked as paid.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        tx_ref = request.form.get('transaction_id', '').strip()
        notes = request.form.get('admin_notes', '').strip()
        payment_date = request.form.get('payment_date', '').strip()
        if not tx_ref:
            flash('Transaction reference is required.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        payout.status = 'paid'
        payout.transaction_id = tx_ref
        payout.admin_notes = notes
        payout.paid_at = datetime.fromisoformat(payment_date) if payment_date else now
        payout.payout_date = payout.paid_at
        _payout_audit(payout, 'paid', admin_user, notes or tx_ref)
        _notify_user(payout.user_id, 'Payout paid successfully', f'Your ${payout.amount:.2f} payout was paid successfully.', admin_user.id)
    else:
        abort(404)

    db.session.commit()
    flash('Payout updated successfully.', 'success')
    return redirect(request.referrer or url_for('admin.admin_payouts'))


@admin_bp.route('/analytics')
@admin_required
def admin_analytics():
    return render_template('admin/admin_analytics.html')


@admin_bp.route('/coupons', methods=['GET', 'POST'])
@admin_required
def admin_coupons():
    if request.method == 'POST':
        try:
            code = request.form.get('code', '').upper().strip()
            description = request.form.get('description', '').strip()
            coupon_type = request.form.get('coupon_type', 'universal')
            discount_type = request.form.get('discount_type', 'percent')
            discount_value = float(request.form.get('discount_value', 0))
            currency = request.form.get('currency', 'USD').upper()
            if currency not in ('USD', 'INR'):
                raise ValueError('Unsupported coupon currency')
            max_uses = request.form.get('max_uses')
            max_uses = int(max_uses) if max_uses and max_uses.strip() else None
            expires_at_str = request.form.get('expires_at')
            
            expires_at = None
            if expires_at_str and expires_at_str.strip():
                expires_at = datetime.fromisoformat(expires_at_str)
            
            existing = Coupon.query.filter_by(code=code, is_deleted=False).first()
            if existing:
                flash(f'Coupon code "{code}" already exists.', 'error')
                return redirect(url_for('admin.admin_coupons'))

            coupon = Coupon(
                code=code,
                description=description,
                coupon_type=coupon_type,
                discount_type=discount_type,
                discount_value=discount_value,
                currency=currency,
                max_uses=max_uses,
                expires_at=expires_at,
                created_by_admin_id=session['user_id']
            )

            if coupon_type == 'influencer':
                influencer_email = request.form.get('influencer_email', '').strip()
                influencer = User.query.filter_by(email=influencer_email).first()
                if not influencer:
                    flash(f'Influencer user with email "{influencer_email}" not found.', 'error')
                    return redirect(url_for('admin.admin_coupons'))
                coupon.influencer_id = influencer.id

            db.session.add(coupon)
            db.session.flush()

            if coupon_type == 'specific':
                assigned_emails = request.form.get('assigned_emails', '').strip()
                if assigned_emails:
                    email_list = [e.strip() for e in assigned_emails.split(',') if e.strip()]
                    invalid_emails = []
                    for email in email_list:
                        user = User.query.filter_by(email=email).first()
                        if user:
                            assignment = CouponAssignment(coupon_id=coupon.id, user_id=user.id)
                            db.session.add(assignment)
                            create_notification(
                                user.id,
                                'New Coupon Available',
                                'A new discount coupon has been added to your account. Use it on your next challenge purchase and save.',
                                'coupon',
                                action_url='/user/my-coupons',
                                icon='gift',
                                admin_id=session.get('user_id'),
                                dedupe_key=f'coupon-assigned:{coupon.id}:{user.id}',
                            )
                        else:
                            invalid_emails.append(email)
                    if invalid_emails:
                        flash(f"Coupon created, but these emails were not found: {', '.join(invalid_emails)}", 'warning')
            elif coupon_type == 'universal':
                notify_all_users(
                    'New Promotion Available',
                    'A new promotional coupon is now available. Visit the coupons section and claim your discount.',
                    'promotion',
                    action_url='/user/my-coupons',
                    icon='money',
                    admin_id=session.get('user_id'),
                    dedupe_key=f'global-coupon:{coupon.id}',
                )

            log = AdminLog(
                admin_id=session['user_id'],
                action='create_coupon',
                target_type='coupon',
                target_id=coupon.id,
                details=f'Created coupon: {code} ({coupon_type})',
                ip_address=request.remote_addr
            )
            db.session.add(log)
            db.session.commit()
            
            flash(f'Coupon "{code}" created successfully!', 'success')
            return redirect(url_for('admin.admin_coupons'))

        except Exception as e:
            db.session.rollback()
            print(f"Error creating coupon: {e}")
            flash('Error creating coupon. Please verify your input.', 'error')
            return redirect(url_for('admin.admin_coupons'))

    coupons = Coupon.query.filter_by(is_deleted=False).order_by(Coupon.created_at.desc()).all()
    return render_template('admin/coupons.html', coupons=coupons)


@admin_bp.route('/coupons/<int:coupon_id>')
@admin_required
def admin_coupon_detail(coupon_id):
    coupon = Coupon.query.filter_by(id=coupon_id, is_deleted=False).first_or_404()
    usages = CouponUsage.query.filter_by(coupon_id=coupon.id).order_by(CouponUsage.used_at.desc()).all()
    total_discount_given = sum(u.discount_amount for u in usages)
    total_revenue_generated = sum(u.final_price for u in usages)
    return render_template('admin/coupon_detail.html', coupon=coupon, usages=usages, total_discount_given=total_discount_given, total_revenue_generated=total_revenue_generated)


@admin_bp.route('/coupons/<int:coupon_id>/delete', methods=['POST'])
@admin_required
def admin_delete_coupon(coupon_id):
    coupon = Coupon.query.filter_by(id=coupon_id, is_deleted=False).first_or_404()
    coupon.is_deleted = True
    coupon.is_active = False
    log = AdminLog(admin_id=session['user_id'], action='delete_coupon', target_type='coupon', target_id=coupon.id, details=f'Soft-deleted coupon: {coupon.code}', ip_address=request.remote_addr)
    db.session.add(log)
    db.session.commit()
    flash(f'Coupon "{coupon.code}" deleted successfully!', 'success')
    return redirect(url_for('admin.admin_coupons'))


@admin_bp.route('/coupons/analytics')
@admin_required
def admin_coupon_analytics():
    total_coupons = Coupon.query.filter_by(is_deleted=False).count()
    active_coupons = Coupon.query.filter_by(is_deleted=False, is_active=True).count()
    now = datetime.now(timezone.utc)
    expired_coupons = Coupon.query.filter(Coupon.is_deleted == False, Coupon.expires_at != None, Coupon.expires_at < now).count()
    usages = CouponUsage.query.order_by(CouponUsage.used_at.asc()).all()
    total_usages = len(usages)
    total_discount_given = sum(u.discount_amount for u in usages)
    total_revenue_generated = sum(u.final_price for u in usages)
    top_coupons = db.session.query(Coupon.code, Coupon.coupon_type, func.count(CouponUsage.id).label('usage_count'), func.sum(CouponUsage.final_price).label('revenue')).join(CouponUsage, CouponUsage.coupon_id == Coupon.id).filter(Coupon.is_deleted == False).group_by(Coupon.id).order_by(db.desc('usage_count')).limit(5).all()
    thirty_days_ago = now - timedelta(days=30)
    timeline_usages = db.session.query(func.date(CouponUsage.used_at).label('date'), func.count(CouponUsage.id).label('count')).filter(CouponUsage.used_at >= thirty_days_ago).group_by(func.date(CouponUsage.used_at)).order_by('date').all()
    timeline_labels = [str(t.date) for t in timeline_usages]
    timeline_values = [int(t.count) for t in timeline_usages]
    return render_template('admin/coupon_analytics.html', total_coupons=total_coupons, active_coupons=active_coupons, expired_coupons=expired_coupons, total_usages=total_usages, total_discount_given=total_discount_given, total_revenue_generated=total_revenue_generated, top_coupons=top_coupons, timeline_labels=timeline_labels, timeline_values=timeline_values)
