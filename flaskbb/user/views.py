# -*- coding: utf-8 -*-
"""
    flaskbb.user.views
    ~~~~~~~~~~~~~~~~~~

    The user view handles the user profile
    and the user settings from a signed in user.

    :copyright: (c) 2014 by the FlaskBB Team.
    :license: BSD, see LICENSE for more details.
"""
import logging

import attr
from flask import Blueprint, flash, redirect, request, url_for, safe_join, current_app
from flask.views import MethodView
from flask_babelplus import gettext as _
from flask_login import current_user, login_required
from pluggy import HookimplMarker
from flaskbb.extensions import db_hub
from hub.models import Token
from hub.utils import get_byond_ckey
import secrets

from flaskbb.user.models import User
from flaskbb.forum.models import UploadedFile
from flaskbb.utils.helpers import register_view, render_template
from flaskbb.utils.requirements import has_permission

import os

from ..core.exceptions import PersistenceError, StopValidation
from .services.factories import (
    change_details_form_factory,
    change_email_form_factory,
    change_password_form_factory,
    details_update_factory,
    email_update_handler,
    password_update_handler,
    settings_form_factory,
    settings_update_handler,
)

impl = HookimplMarker("flaskbb")

logger = logging.getLogger(__name__)


@attr.s(frozen=True, cmp=False, hash=False, repr=True)
class UserSettings(MethodView):
    form = attr.ib(factory=settings_form_factory)
    settings_update_handler = attr.ib(factory=settings_update_handler)

    decorators = [login_required]

    def get(self):
        return self.render()

    def post(self):
        if self.form.validate_on_submit():
            try:
                self.settings_update_handler.apply_changeset(
                    current_user, self.form.as_change()
                )
            except StopValidation as e:
                self.form.populate_errors(e.reasons)
                return self.render()
            except PersistenceError:
                logger.exception("Error while updating user settings")
                flash(_("Error while updating user settings"), "danger")
                return self.redirect()

            flash(_("Settings updated."), "success")
            return self.redirect()
        return self.render()

    def render(self):
        return render_template("user/general_settings.html", form=self.form)

    def redirect(self):
        return redirect(url_for("user.settings"))


@attr.s(frozen=True, hash=False, cmp=False, repr=True)
class ChangePassword(MethodView):
    form = attr.ib(factory=change_password_form_factory)
    password_update_handler = attr.ib(factory=password_update_handler)
    decorators = [login_required]

    def get(self):
        return self.render()

    def post(self):
        if self.form.validate_on_submit():
            try:
                self.password_update_handler.apply_changeset(
                    current_user, self.form.as_change()
                )
            except StopValidation as e:
                self.form.populate_errors(e.reasons)
                return self.render()
            except PersistenceError:
                logger.exception("Error while changing password")
                flash(_("Error while changing password"), "danger")
                return self.redirect()

            flash(_("Password updated."), "success")
            return self.redirect()
        return self.render()

    def render(self):
        return render_template("user/change_password.html", form=self.form)

    def redirect(self):
        return redirect(url_for("user.change_password"))


@attr.s(frozen=True, cmp=False, hash=False, repr=True)
class ChangeEmail(MethodView):
    form = attr.ib(factory=change_email_form_factory)
    update_email_handler = attr.ib(factory=email_update_handler)
    decorators = [login_required]

    def get(self):
        return self.render()

    def post(self):
        if self.form.validate_on_submit():
            try:
                self.update_email_handler.apply_changeset(
                    current_user, self.form.as_change()
                )
            except StopValidation as e:
                self.form.populate_errors(e.reasons)
                return self.render()
            except PersistenceError:
                logger.exception("Error while updating email")
                flash(_("Error while updating email"), "danger")
                return self.redirect()

            flash(_("Email address updated."), "success")
            return self.redirect()
        return self.render()

    def render(self):
        return render_template("user/change_email.html", form=self.form)

    def redirect(self):
        return redirect(url_for("user.change_email"))


@attr.s(frozen=True, repr=True, cmp=False, hash=False)
class ChangeUserDetails(MethodView):
    form = attr.ib(factory=change_details_form_factory)
    details_update_handler = attr.ib(factory=details_update_factory)
    decorators = [login_required]

    def get(self):
        return self.render()

    def post(self):

        if self.form.validate_on_submit():
            try:
                self.details_update_handler.apply_changeset(
                    current_user, self.form.as_change()
                )
            except StopValidation as e:
                self.form.populate_errors(e.reasons)
                return self.render()
            except PersistenceError:
                logger.exception("Error while updating user details")
                flash(_("Error while updating user details"), "danger")
                return self.redirect()

            flash(_("User details updated."), "success")
            return self.redirect()
        return self.render()

    def render(self):
        return render_template("user/change_user_details.html", form=self.form)

    def redirect(self):
        return redirect(url_for("user.change_user_details"))

class UserUploads(MethodView):
    decorators = [login_required]

    def get(self):
        files = UploadedFile.query.filter_by(user_id=current_user.id).all()
        return render_template("user/user_uploads.html",files=files)

class DeleteFile(MethodView):
    decorators = [login_required]

    def post(self):
        file_id = request.args.get("file_id",0,type=int)
        file_record = UploadedFile.query.filter_by(id=file_id).first_or_404()
        file_owner = User.query.filter_by(id=file_record.user_id).first_or_404()
        
        if not (file_owner.id == current_user.id or has_permission(current_user, "admin")):
            logger.warn("File {}(owned by:{}, discord:{}) was tried to be deleted by {}(discord:{})".format(file_record, file_owner, file_owner.discord, current_user.username, current_user.discord))
            return redirect(url_for("user.user_uploads"))

        path = safe_join(current_app.config["UPLOAD_FOLDER"], file_owner.discord, file_record.current_name)
        
        logger.info("File {}(owned by:{}, discord:{})) was deleted by {}(discord:{})".format(file_record, file_owner, file_owner.discord, current_user.username, current_user.discord))

        os.remove(path)
        file_record.delete()

        flash(_("File deleted."), "success")
        return redirect(url_for("user.user_uploads"))
        
class AllUserTopics(MethodView):  # pragma: no cover
    decorators = [login_required]

    def get(self, userid):
        page = request.args.get("page", 1, type=int)
        user = User.query.filter_by(id=userid).first_or_404()
        topics = user.all_topics(page, current_user)
        return render_template("user/all_topics.html", user=user, topics=topics)


class AllUserPosts(MethodView):  # pragma: no cover
    decorators = [login_required]

    def get(self, userid):
        page = request.args.get("page", 1, type=int)
        user = User.query.filter_by(id=userid).first_or_404()
        posts = user.all_posts(page, current_user)
        return render_template("user/all_posts.html", user=user, posts=posts)


class UserProfile(MethodView):  # pragma: no cover
    decorators = [login_required]

    def get(self, userid):
        user = User.query.filter_by(id=userid).first_or_404()
        return render_template("user/profile.html", user=user)

class GenerateToken(MethodView):  # pragma: no cover
    decorators = [login_required]

    def get(self, userid):
        
        if(get_byond_ckey(current_user)):
            flash("Ваш дискорд уже привязан к аккаунту {}".format(get_byond_ckey(current_user)))
            return redirect(url_for("user.profile", userid=current_user.id))

        Token.query.filter(Token.discord_user_id == current_user.discord).delete()
        new_token = Token()
        new_token.token = secrets.token_hex(16)
        new_token.discord_user_id = current_user.discord


        db_hub.session.add(new_token)
        db_hub.session.commit()

        db_hub.session.refresh(new_token)
        db_hub.session.expunge_all()

        flash("Ваш токен {}. Чтобы выполнить привязку BYOND аккаунта, введите его, с помощью консольной команды `.chaotic-token` на одном из наших серверов.".format(new_token.token))
        return redirect(url_for("user.profile", userid=current_user.id))


@impl(tryfirst=True)
def flaskbb_load_blueprints(app):
    user = Blueprint("user", __name__)
    register_view(
        user, routes=["/settings/email"], view_func=ChangeEmail.as_view("change_email")
    )
    register_view(
        user, routes=["/settings/general"], view_func=UserSettings.as_view("settings")
    )
    register_view(
        user,
        routes=["/settings/password"],
        view_func=ChangePassword.as_view("change_password"),
    )
    register_view(
        user,
        routes=["/settings/user-details"],
        view_func=ChangeUserDetails.as_view("change_user_details"),
    )
    register_view(
        user, routes=["/settings/uploads"], view_func=UserUploads.as_view("user_uploads")
    )
    register_view(
        user, routes=["/settings/uploads/delete"], view_func=DeleteFile.as_view("delete_file")
    )

    register_view(
        user,
        routes=["/user<userid>/posts"],
        view_func=AllUserPosts.as_view("view_all_posts"),
    )
    register_view(
        user,
        routes=["/user<userid>/topics"],
        view_func=AllUserTopics.as_view("view_all_topics"),
    )
    register_view(
        user,
        routes=["/user<userid>/generate-token"],
        view_func=GenerateToken.as_view("generate_token"),
    )

    register_view(
        user, routes=["/user<userid>"], view_func=UserProfile.as_view("profile")
    )

    app.register_blueprint(user, url_prefix=app.config["USER_URL_PREFIX"])
