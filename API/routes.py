from . import app
from fastapi.responses import JSONResponse, StreamingResponse
from firebase_models import Place, User
from fastapi import Form, Depends, File
from Util import create_user, authenticate_user, create_access_token, get_current_user, \
    calculate_boundaries
from typing import Annotated
from fastapi.security import OAuth2PasswordBearer
from geopy.distance import geodesic
from google.cloud.firestore_v1._helpers import GeoPoint
from firebase_models import bucket

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


@app.get("/check-status", tags=["Status"])
async def status():
    return JSONResponse(content={"API is working": "True"}, status_code=200)


@app.post("/add-place", tags=["Places"])
async def add_place(title: Annotated[str, Form()], rating: Annotated[float, Form()],
                    description: Annotated[str, Form()], user_ids: Annotated[str, Form()],
                    geo_point: Annotated[str, Form()], approved: Annotated[bool, Form()],
                    image_references: Annotated[str, Form()]):
    geo_point = geo_point.split(", ")
    user_ids = user_ids.split(", ")
    image_references = image_references.split(", ")
    place = Place(
        title=title,
        rating=rating,
        description=description,
        user_ids=user_ids,
        geo_point=GeoPoint(latitude=float(geo_point[0]), longitude=float(geo_point[1])),
        approved=approved,
        image_references=image_references
    )
    place.save()
    return JSONResponse(content={f"{place.id}": f"{title}"}, status_code=200)


@app.post("/update-place-location/{place_id}", tags=["Places"])
async def update_location(place_id: str, lat: Annotated[str, Form()], lon: Annotated[str, Form()]):
    p = (Place.collection.filter("id", "==", place_id)).get()
    if p:
        p.geo_point = GeoPoint(latitude=float(lat), longitude=float(lon))
        p.save()
        return JSONResponse(content={"message": f"Place with {place_id} was updated"}, status_code=200)
    else:
        return JSONResponse(content={"message": "There is no such place"}, status_code=404)


@app.get("/get-place/{place_id}", tags=["Places"])
async def get_place_by_name(place_id: str):
    # Executing the query
    places_query = (
        Place.collection.filter("id", "==", place_id)
    ).fetch()

    for p in places_query:
        return p.to_dict()


@app.post("/upload-image", tags=["Media"])
async def upload_image(image: bytes = File(), place_id: str = Form(), image_extension: str = Form()):
    blobs = bucket.list_blobs(prefix=place_id)
    s = sum(1 for _ in blobs)
    file_name = f"{place_id}/{s}.{image_extension}"
    blob = bucket.blob(file_name)
    blob.upload_from_string(image, content_type=f"image/{image_extension}")


@app.get("/get-images-list/{place_id}", tags=["Media"])
async def get_images(place_id: str):
    result = {
        "image_ref": []
    }
    for b in bucket.list_blobs(prefix=place_id):
        filename = str(b.name)
        result["image_ref"].append(filename[filename.find("/") + 1:len(filename)])
    return result


@app.get("/images/{place_id}/{image_name}", tags=["Media"])
async def image_by_place_id(place_id: str, image_name: str):
    for b in bucket.list_blobs(prefix=place_id):
        byte_file = b.download_as_bytes()
        filename = str(b.name)
        current_name = filename[filename.find("/") + 1:len(filename)]
        if current_name == image_name:
            async def stream_image():
                yield byte_file

            return StreamingResponse(stream_image(), media_type=b.content_type)


@app.get("/get-user/{email}", tags=["Users"])
async def get_user_by_name(email: str):
    # Executing the query
    users_query = (
        User.collection.filter("email", "==", email)
    ).fetch()

    result = {}

    for p in users_query:
        result[p.id] = p.email

    return result


@app.post("/register", tags=["Authentication"])
async def register(email: Annotated[str, Form()], password: Annotated[str, Form()]):
    existing_user = User.collection.filter("email", "==", email).get()
    if existing_user:
        return JSONResponse(content={"message": "User with such email already exists"}, status_code=400)
    create_user(User(email=email, password=password))
    return {"message": "User registered"}


@app.post("/login", tags=["Authentication"])
async def login(email: Annotated[str, Form()], password: Annotated[str, Form()]):
    user = authenticate_user(email, password)
    if not user:
        return JSONResponse(content={"message": "Invalid username or password"}, status_code=401)
    access_token = create_access_token(user)
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/protected", tags=["Authentication"])
async def protected_route(user: User = Depends(get_current_user)):
    return {"message": f"Hello, {user.name}! This is a protected route."}


@app.get("/near-places", tags=["Places"])
async def get_near_places(user_lat: float, user_lon: float):
    # check documentation and postman request in notion for this one
    search_scope = calculate_boundaries(user_lat, user_lon, 1)

    places = Place.collection \
        .filter("geo_point", ">=", search_scope["minimal_point"]) \
        .filter("geo_point", "<=", search_scope["maximal_point"]) \
        .fetch()

    result = {}

    for p in places:
        result[p.id] = geodesic((user_lat, user_lon), (p.geo_point.latitude, p.geo_point.longitude)).meters

    return result


@app.get("/search-place-by-rating/{rating_range}", tags=["Places"])
async def search_by_rating(rating_range: int):
    queried_places = Place.collection.filter("rating", ">=", rating_range).fetch()
    result = {}
    for place in queried_places:
        result[place.id] = place.rating

    return result
