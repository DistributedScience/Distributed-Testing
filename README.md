# Distributed-Testing

[Distributed-Something](https://github.com/DistributedScience/Distributed-Something) is an app to run encapsulated docker containers that do... something in the Amazon Web Services (AWS) infrastructure.
We are interested in scientific image analysis so we have used it for [CellProfiler](https://github.com/DistributedScience/Distributed-CellProfiler), [Fiji](https://github.com/DistributedScience/Distributed-Fiji), and [BioFormats2Raw](https://github.com/DistributedScience/Distributed-OmeZarrMaker).
You can use it for whatever you want!

[Distributed-HelloWorld](https://github.com/DistributedScience/Distributed-HelloWorld) uses it to make a simple app that lets you say hello to the world, as well as list some of your favorite things.

Here, we reimplement Distributed-HelloWorld, with a testing suite.

Like any Distributed-Something applicaton, to make it run in AWS, a user still needs to add their AWS-account specific information.

The test suite however is run locally, using [moto](https://docs.getmoto.org/en/latest/) to mock AWS infastructure. This lets you make changes and test them without concern for breaking thins on live AWS infrastructure (and incur the associated costs).

## Tests

To run the tests, setup a virtual environment using your tool of choice (eg `venv`. `conda`, etc), and install the depedencies:

    pip install -r requirements.txt

Run `pytest` in the terminal.

Happy Distributing!

## Documentation
Full Distributed-Something documentation is available on our [Documentation Website](https://distributedscience.github.io/Distributed-Something).
