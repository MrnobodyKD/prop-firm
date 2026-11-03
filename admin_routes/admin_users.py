from flask import render_template, request, redirect, url_for, flash, session, jsonify, abort, Response, send_file
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, extract, or_
from models import db, User, ChallengeTemplate, ChallengePurchase, Payout, PayoutAuditLog, FAQ, SupportTicket, TicketMessage, Payment, AdminLog, Notification, UserNotification, NotificationTemplate, Coupon, CouponUsage, CouponAssignment, ProgressionRequest, RulebookSection
from . import admin_bp, admin_required, get_current_moderator, log_moderator_activity
from notification_service import create_notification
import secrets
import csv
import io
import json

from . import _admin_name, _notify_user, _notify_challenge_passed, _notify_challenge_breached, _activate_progression_stage, _payout_audit, _eligible_funded_count, _payout_stats

# Helper to get current user ID (works for both admin and moderator)
def _current_user_id():
    return session.get('user_id') or session.get('moderator_id')

# Helper to log moderator actions easily
def _log_if_moderator(module, action, description=None, target_type=None, target_id=None, before_state=None, after_state=None, status='success'):
    """Log action only if current user is a moderator"""
    if 'moderator_id' in session:
        try:
            log_moderator_activity(
                moderator_id=session['moderator_id'],
                module=module,
                action=action,
                description=description,
                target_type=target_type,
                target_id=target_id,
                before_state=before_state,
                after_state=after_state,
                status=status
            )
        except:
            pass  # Don't break functionality if logging fails

@admin_bp.route('/users')
@admin_required
def admin_users():
    users = []
    admin_count = User.query.filter_by(is_admin=True).count()
    return render_template('admin/users.html', users=users, admin_count=admin_count)


@admin_bp.route('/ban_user/<int:user_id>')
@admin_required
def admin_ban_user(user_id):
    user = User.query.get(user_id)
    if user and not user.is_admin:
        before_state = {'is_banned': user.is_banned}
        user.is_banned = True
        db.session.commit()
        _log_if_moderator('users', 'banned_user', f'Banned user {user.email}', 'user', user.id, before_state, {'is_banned': True})
        flash(f'User {user.email} has been banned.', 'success')
    else:
        flash('Cannot ban admin users.', 'error')
    return redirect(request.referrer or url_for('admin.admin_users'))


@admin_bp.route('/unban_user/<int:user_id>')
@admin_required
def admin_unban_user(user_id):
    user = User.query.get(user_id)
    if user and not user.is_admin:
        before_state = {'is_banned': user.is_banned}
        user.is_banned = False
        db.session.commit()
        _log_if_moderator('users', 'unbanned_user', f'Unbanned user {user.email}', 'user', user.id, before_state, {'is_banned': False})
        flash(f'User {user.email} has been unbanned.', 'success')
    else:
        flash('Cannot modify admin users.', 'error')
    return redirect(request.referrer or url_for('admin.admin_users'))


@admin_bp.route('/verify_phone/<int:user_id>')
@admin_required
def admin_verify_phone(user_id):
    user = User.query.get_or_404(user_id)
    before_state = {'phone_verified': user.phone_verified}
    user.phone_verified = True
    user.phone_verification_code = None
    db.session.commit()
    _log_if_moderator('users', 'verified_phone', f'Verified phone for {user.email}', 'user', user.id, before_state, {'phone_verified': True})
    flash(f'Phone number for {user.email} marked as verified.', 'success')
    return redirect(request.referrer or url_for('admin.admin_users'))


@admin_bp.route('/bulk_action', methods=['POST'])
@admin_required
def admin_bulk_action():
    user_ids = request.form.getlist('user_ids')
    action = request.form.get('action')
    
    users = User.query.filter(User.id.in_(user_ids), User.is_admin == False).all()
    
    if action == 'ban':
        for user in users:
            user.is_banned = True
        db.session.commit()
        _log_if_moderator('users', 'bulk_banned', f'Bulk banned {len(users)} users', 'users_batch', None, None, {'count': len(users)})
        flash(f'Banned {len(users)} users.', 'success')
    elif action == 'unban':
        for user in users:
            user.is_banned = False
        db.session.commit()
        _log_if_moderator('users', 'bulk_unbanned', f'Bulk unbanned {len(users)} users', 'users_batch', None, None, {'count': len(users)})
        flash(f'Unbanned {len(users)} users.', 'success')
    elif action == 'delete':
        for user in users:
            db.session.delete(user)
        db.session.commit()
        _log_if_moderator('users', 'bulk_deleted', f'Bulk deleted {len(users)} users', 'users_batch', None, None, {'count': len(users)})
        flash(f'Deleted {len(users)} users.', 'success')
    
    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/api/users')
@admin_required
def api_users():
    try:
        page = max(int(request.args.get('page', 1)), 1)
    except (ValueError, TypeError):
        page = 1
    
    try:
        per_page = min(max(int(request.args.get('per_page', 25)), 10), 100)
    except (ValueError, TypeError):
        per_page = 25
        
    search = request.args.get('search', '').strip()
    query = User.query
    if search:
        like = f"%{search}%"
        query = query.filter(
            (User.first_name.ilike(like)) |
            (User.last_name.ilike(like)) |
            (User.email.ilike(like)) |
            (User.phone.ilike(like))
        )
    account_status = request.args.get('account_status', 'all')
    if account_status != 'all':
        if account_status == 'active':
            query = query.filter(User.is_active == True)
        elif account_status == 'banned':
            query = query.filter(User.is_banned == True)
        elif account_status == 'new':
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            query = query.filter(User.created_at >= week_ago)
        
    sort = request.args.get('sort', 'newest')
    if sort == 'oldest':
        query = query.order_by(User.created_at.asc())
    else:
        query = query.order_by(User.created_at.desc())
        
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    users_data = []
    for u in pagination.items:
        users_data.append({
            'id': u.id, 'first_name': u.first_name, 'last_name': u.last_name,
            'email': u.email, 'phone': u.phone or 'N/A',
            'city': getattr(u, 'city', 'N/A'), 'state': getattr(u, 'state', 'N/A'),
            'country': getattr(u, 'country', 'N/A'),
            'status': 'banned' if u.is_banned else 'active',
            'created_at': u.created_at.isoformat() if u.created_at else None,
        })
    return jsonify({
        'success': True, 'users': users_data,
        'total': pagination.total, 'pages': pagination.pages, 'current_page': pagination.page,
    })


@admin_bp.route('/user/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    user = User.query.get(user_id)
    if not user:
        abort(404)
    from email_service import get_or_create_preferences
    from models import EmailTemplate
    challenges = getattr(user, 'challenge_purchases', []) if hasattr(user, 'challenge_purchases') else []
    payments = getattr(user, 'payments', []) if hasattr(user, 'payments') else []
    support_tickets = getattr(user, 'support_tickets', []) if hasattr(user, 'support_tickets') else []
    payouts = getattr(user, 'payouts', []) if hasattr(user, 'payouts') else []
    email_templates = EmailTemplate.query.filter_by(is_active=True).order_by(EmailTemplate.name).all()
    email_preference = get_or_create_preferences(user.id)
    
    total_spent = sum(p.amount for p in payments if p.status.upper() == 'SUCCESS')
    total_purchases = len([p for p in payments if p.status.upper() == 'SUCCESS'])
    total_payouts = sum(p.amount for p in payouts if p.status.upper() == 'SUCCESS' or p.status.upper() == 'PAID')
    
    referrals = []
    return render_template('admin/user_detail.html', user=user,
                           challenges=challenges, payments=payments,
                           support_tickets=support_tickets, referrals=referrals,
                           total_spent=total_spent, total_purchases=total_purchases,
                           total_payouts=total_payouts,
                           email_templates=email_templates, email_preference=email_preference)


def get_challenges_dashboard_data():
    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    expiring_threshold = now_utc + timedelta(days=3)

    total_revenue = db.session.query(db.func.sum(ChallengeTemplate.price)).filter(
        ChallengePurchase.challenge_template_id == ChallengeTemplate.id,
        ChallengePurchase.status.in_(['active', 'passed', 'failed', 'pending_credentials'])
    ).scalar() or 0
    
    total_purchases = ChallengePurchase.query.count()
    today_purchases = ChallengePurchase.query.filter(ChallengePurchase.purchase_date >= today_start).count()
    active_challenges = ChallengePurchase.query.filter(ChallengePurchase.status.in_(['active', 'funded'])).count()
    passed_phase1 = ChallengePurchase.query.filter_by(status='passed', current_phase=1).count()
    passed_phase2 = ChallengePurchase.query.filter_by(status='passed', current_phase=2).count()
    funded_accounts = ChallengePurchase.query.filter_by(status='funded').count()
    failed_accounts = ChallengePurchase.query.filter(ChallengePurchase.status.in_(['failed', 'breached'])).count()
    pending_phase2_requests = ProgressionRequest.query.filter_by(request_type='phase2', status='pending').count()
    pending_funded_requests = ProgressionRequest.query.filter_by(request_type='funded', status='pending').count()
    approved_requests = ProgressionRequest.query.filter_by(status='approved').count()
    declined_requests = ProgressionRequest.query.filter_by(status='declined').count()
    expiring_soon = ChallengePurchase.query.filter(
        ChallengePurchase.status.in_(['active', 'funded']),
        ChallengePurchase.end_date <= expiring_threshold, ChallengePurchase.end_date >= now_utc
    ).count()
    pending_payouts = db.session.query(db.func.sum(Payout.amount)).filter(Payout.status == 'pending').scalar() or 0
    payout_eligible = Payout.query.filter_by(status='pending').count()
    
    return {
        'total_revenue': total_revenue, 'total_purchases': total_purchases,
        'today_purchases': today_purchases, 'pending_payouts': pending_payouts,
        'active_challenges': active_challenges, 'passed_phase1': passed_phase1,
        'passed_phase2': passed_phase2, 'funded_accounts': funded_accounts,
        'failed_accounts': failed_accounts, 'pending_phase2_requests': pending_phase2_requests,
        'pending_funded_requests': pending_funded_requests, 'approved_requests': approved_requests,
        'declined_requests': declined_requests, 'expiring_soon': expiring_soon,
        'payout_eligible': payout_eligible
    }


@admin_bp.route('/user/<int:user_id>/reset-password', methods=['POST'])
def admin_reset_user_password(user_id):
    from werkzeug.security import generate_password_hash
    user = User.query.get_or_404(user_id)
    new_password = ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(12))
    user.set_password(new_password)
    db.session.commit()
    _log_if_moderator('users', 'reset_password', f'Reset password for {user.email}', 'user', user.id)
    flash(f'Password reset to: {new_password}', 'success')
    return redirect(url_for('admin.admin_user_detail', user_id=user_id))


@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    user_email = user.email
    db.session.delete(user)
    db.session.commit()
    _log_if_moderator('users', 'deleted_user', f'Deleted user {user_email}', 'user', user_id)
    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/user/<int:user_id>/analytics')
@admin_required
def admin_user_analytics(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('admin/admin_user_analytics.html', user_id=user_id, user_name=user.get_full_name())
