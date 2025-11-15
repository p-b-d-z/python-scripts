import jwt

def get_cloudflare_user(request):
    jwt_token = request.headers.get('Cf-Access-Jwt-Assertion')
    if not jwt_token:
        return None

    try:
        claims = jwt.decode(jwt_token, options={'verify_signature': False}, algorithms=['RS256'])
        user_email = claims.get('email', None)
        return {'email': user_email}
    except jwt.PyJWTError:
        return None
