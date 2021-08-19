.DEFAULT_GOAL := docker-image

BASE_IMAGE_NAME 		:= inmantaci/containerlab-vms
PACKAGE_VERSION_SCRIPT	:= -c "import pkg_resources; v = pkg_resources.get_distribution('containerlab-vms').version; print(v)"

isort = isort src vms
black = black src vms
flake8 = flake8 src vms

.PHONY: install
install:
	pip install -U pip poetry
	poetry install

.PHONY: format
format:
	$(isort)
	$(black)
	$(flake8)

.PHONY: mypy
mypy:
	MYPYPATH=src python -m mypy --html-report mypy/out/clab_vm_startup -p clab_vm_startup; \
	for d in vms/*/; do \
		MYPYPATH=vms python -m mypy --html-report mypy/out/$$d $$d/launch.py; \
	done

docker-image:
	docker build -t ${BASE_IMAGE_NAME}:tmp .
	docker tag ${BASE_IMAGE_NAME}:tmp ${BASE_IMAGE_NAME}:$$(docker run --rm ${BASE_IMAGE_NAME}:tmp ${PACKAGE_VERSION_SCRIPT})
	docker rmi ${BASE_IMAGE_NAME}:tmp
