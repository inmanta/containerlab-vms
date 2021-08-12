BASE_IMAGE_NAME 		:= inmantaci/containerlab-vms
PACKAGE_VERSION_SCRIPT	:= -c "import pkg_resources; v = pkg_resources.get_distribution('containerlab-vms').version; print(v)"

docker-image:
	docker build -t ${BASE_IMAGE_NAME}:tmp .
	docker tag ${BASE_IMAGE_NAME}:tmp ${BASE_IMAGE_NAME}:$$(docker run --rm ${BASE_IMAGE_NAME}:tmp ${PACKAGE_VERSION_SCRIPT})
	docker rmi ${BASE_IMAGE_NAME}:tmp
