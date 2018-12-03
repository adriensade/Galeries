from . import api
from flask_restplus import Resource, reqparse
import re
import os, datetime
from ..models import User
from ..services import UserService
from ..persistence import UserDAO
import json
from flask import jsonify, request, Response
from .. import db, app
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity


jwt = JWTManager(app)

@jwt.user_claims_loader
def add_claims_to_access_token(user):
    return {
        "username" : user.username,
        "firstname" : user.firstname,
        "lastname" : user.lastname,
        "roles" : ["USER", "ADMIN"] if user.admin else ["USER"]
    }

@jwt.user_identity_loader
def user_identity(user):
    return user.id

# Returned user accessed using the get_current_user() function, or directly with the current_user LocalProxy
@jwt.user_loader_callback_loader
def user_loader_callback(identity):
    return User.query.filter_by(id=identity).first()


@api.route('/hello')
class HelloWorld(Resource):
    def get(self):
        return {'hello': 'world'}, 213

@api.route('/login')
@api.doc(params=    {
                        'email': 'the first part of the email. Example : jean.dupont',
                        'password': 'your password'
                    })
class Login(Resource):
    @api.response(200, 'Success')
    @api.response(400, 'Request incorrect')
    @api.response(403, 'Not authorized')
    @api.response(401, 'User not identified')
    def post(self):
        if not request.is_json:
            return {"msg": "Missing JSON in request"}, 400

        email = request.json.get('email', None)
        password = request.json.get('password', None)
        if not email:
            return {"msg": "Missing email parameter"}, 400
        if not password:
            return {"msg": "Missing password parameter"}, 400

        user = User.query.filter_by(email=email).first()

        if user is None:
            return {"msg": "Identifiants incorrectes"}, 401
        if not user.email_confirmed:
            if (datetime.datetime.utcnow()-user.created).total_seconds() > 3600:
                db.session.delete(user)
                db.session.commit()
            else:
                return {"msg": "Compte en attente de confirmation par email"}, 403
        if user.check_password(password):
            app.logger.debug("User authenticating on API :", user)
            access_token = create_access_token(identity=user)
            return {"token": access_token}, 200
        else:
            return {"msg": "Bad email or password"}, 401

@api.route('/register')
class Register(Resource):
    def post(self):
        lastname = request.json.get('lastname')
        firstname = request.json.get('firstname')
        username = request.json.get('email')
        password = request.json.get('password')
        promotion = request.json.get('promotion')
        if password != request.json.get('confirmation_password'):
            return {"msg": "Les deux mot de passe ne correspondent pas"}, 401
        elif not re.fullmatch(r"[a-z0-9\-]+\.[a-z0-9\-]+", username):
            return {"msg": "Adresse non valide"}, 401
        else:
            try:
                new_user = UserService.register(username, firstname, lastname, password, promotion)
            except ValueError:
                return {"msg": "Il existe déjà un compte pour cet adresse email"}, 401
        return {"msg": "utilisateur créé"}, 200


@api.route('/reset/')
class ResetPasswordSendMail(Resource):
    def post(self):
        email = request.json.get('email')
        UserService.reset(email)
        return {"msg": "Si un compte est associé à cette adresse, un mail a été envoyé"}, 200

@api.route('/reset/<token>')
class PasswordResetForm(Resource):
    def post(self, token):

        try:
            user_id = UserService.get_id_from_token(token)
            if user_id is None:
                abort(404)
        except BadSignature:
            abort(404)
        except SignatureExpired :
            return  {
                        "title": "Le token est expiré",
                        "body": "Tu as dépassé le délai de 24h."
                    }, 401
        user = UserDAO.get_by_id(user_id)
        if user is None:
            return  {
                        "title": "Erreur - Aucun utilisateur correspondant",
                        "body": "Le compte associé n'existe plus"
                    }, 401
        if request.method == 'POST':
            new_password = request.json.get('new_password')
            if new_password != request.json.get('confirmation_password'):
                return {"msg": "Les deux mots de passe ne correspondent pas"}, 401
            else:
                user.set_password(new_password)
                db.session.add(user)
                db.session.commit()
                return {"msg": "Mot de passe réinitialisé avec succès"}, 200

        return  {
                    "msg": "utilisateur identifié",
                    "firstname": user.firstname,
                    "lastname": user.lastname
                }, 201
