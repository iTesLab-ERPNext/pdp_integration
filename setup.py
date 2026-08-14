from setuptools import find_packages, setup

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

with open("pdp_integration/__init__.py", encoding="utf-8") as f:
	version_line = [l for l in f.read().splitlines() if l.startswith("__version__")]
	version = version_line[0].split("=")[1].strip().strip('"').strip("'") if version_line else "0.0.1"

setup(
	name="pdp_integration",
	version=version,
	description="SuperPDP (French e-invoicing PDP) integration for ERPNext",
	author="Your Organization",
	author_email="dev@example.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires,
)
