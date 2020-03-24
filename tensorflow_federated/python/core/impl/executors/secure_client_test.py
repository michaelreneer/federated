import asyncio
from typing import Tuple

from absl.testing import absltest
from absl.testing import parameterized
import tensorflow as tf

from tensorflow_federated.proto.v0 import computation_pb2 as pb
from tensorflow_federated.python.common_libs import anonymous_tuple
from tensorflow_federated.python.core.api import computation_types
from tensorflow_federated.python.core.api import computations
from tensorflow_federated.python.core.api import intrinsics
from tensorflow_federated.python.core.api import placements
from tensorflow_federated.python.core.impl import computation_impl
from tensorflow_federated.python.core.impl import test as core_test
from tensorflow_federated.python.core.impl.compiler import building_block_factory
from tensorflow_federated.python.core.impl.compiler import building_blocks
from tensorflow_federated.python.core.impl.compiler import intrinsic_defs
from tensorflow_federated.python.core.impl.compiler import type_factory
from tensorflow_federated.python.core.impl.compiler import type_serialization
from tensorflow_federated.python.core.impl.executors import default_executor
from tensorflow_federated.python.core.impl.executors import eager_tf_executor
from tensorflow_federated.python.core.impl.executors import executor_test_utils
from tensorflow_federated.python.core.impl.executors import federating_executor
from tensorflow_federated.python.core.impl.executors import reference_resolving_executor


tf.compat.v1.enable_v2_behavior()


def _make_test_executor(
    num_clients=1,
    use_reference_resolving_executor=False,
) -> federating_executor.FederatingExecutor:
  bottom_ex = eager_tf_executor.EagerTFExecutor()
  if use_reference_resolving_executor:
    bottom_ex = reference_resolving_executor.ReferenceResolvingExecutor(
        bottom_ex)
  return federating_executor.FederatingExecutor({
      placements.SERVER: bottom_ex,
      placements.CLIENTS: [bottom_ex for _ in range(num_clients)],
      None: bottom_ex
  })


Runtime = Tuple[asyncio.AbstractEventLoop,
                federating_executor.FederatingExecutor]


def _make_test_runtime(num_clients=1,
                       use_reference_resolving_executor=False) -> Runtime:
  """Creates a test runtime consisting of an event loop and test executor."""
  loop = asyncio.get_event_loop()
  ex = _make_test_executor(
      num_clients=num_clients,
      use_reference_resolving_executor=use_reference_resolving_executor)
  return loop, ex


def _run_comp_with_runtime(comp, runtime: Runtime):
  """Runs a computation using the provided runtime."""
  loop, ex = runtime

  async def call_value():
    return await ex.create_call(await ex.create_value(comp))

  return loop.run_until_complete(call_value())


def _run_test_comp(comp, num_clients=1, use_reference_resolving_executor=False):
  """Runs a computation (unapplied TFF function) using a test runtime."""
  runtime = _make_test_runtime(
      num_clients=num_clients,
      use_reference_resolving_executor=use_reference_resolving_executor)
  return _run_comp_with_runtime(comp, runtime)


def _run_test_comp_produces_federated_value(
    test_instance,
    comp,
    num_clients=1,
    use_reference_resolving_executor=False,
):
  """Runs a computation (unapplied TFF function) using a test runtime.

  This is similar to _run_test_comp, but the result is asserted to be a
  FederatedValue and computed.

  Args:
    test_instance: A class with the standard unit testing assertions.
    comp: The computation to run.
    num_clients: The number of clients to use when computing `comp`.
    use_reference_resolving_executor: Whether or not to include an executor
      to resolve references.

  Returns:
    The result of running the computation.
  """
  loop, ex = _make_test_runtime(
      num_clients=num_clients,
      use_reference_resolving_executor=use_reference_resolving_executor)
  val = _run_comp_with_runtime(comp, (loop, ex))
  test_instance.assertIsInstance(val,
                                 federating_executor.FederatingExecutorValue)
  return loop.run_until_complete(val.compute())


def _produce_test_value(
    value,
    type_spec=None,
    num_clients=1,
    use_reference_resolving_executor=False,
):
  """Produces a TFF value using a test runtime."""
  loop, ex = _make_test_runtime(
      num_clients=num_clients,
      use_reference_resolving_executor=use_reference_resolving_executor)
  return loop.run_until_complete(ex.create_value(value, type_spec=type_spec))


class SecureClientTest(parameterized.TestCase):

  def test_federated_secure_client(self):
    @computations.tf_computation(tf.int32, tf.int32)
    def add_numbers(x, y):
      return x + y

    @computations.federated_computation
    def comp():
      return intrinsics.federated_reduce(
          intrinsics.federated_value(10, placements.CLIENTS), 
          0, add_numbers)

    result = _run_test_comp_produces_federated_value(self, comp, num_clients=3)
    self.assertEqual(result.numpy(), 30)

  def test_federated_zip_secure_client_values(self):
    @computations.tf_computation(tf.int32, tf.int32)
    def add_numbers(x, y):
      return x + y

    @computations.tf_computation(tf.int32, tf.int32)
    def encrypt_tensor(x, y):
      return tf.add(x, y)

    @computations.federated_computation
    def comp():
      return intrinsics.federated_reduce(
        intrinsics.federated_map(encrypt_tensor,
          intrinsics.federated_value((10, 10), placements.CLIENTS)), 
          0, add_numbers)

    result = _run_test_comp_produces_federated_value(self, comp, num_clients=3)
    self.assertEqual(result.numpy(), 60)

  def test_federated_zip_secure_client_values_v2(self):
    @computations.tf_computation(tf.int32, tf.int32)
    def add_numbers(x, y):
      return x + y

    @computations.tf_computation(tf.int32, tf.int32)
    def encrypt_tensor(x, y):
      return tf.add(x, y)

    @computations.federated_computation
    def comp():
      return intrinsics.federated_reduce(
        intrinsics.federated_map(encrypt_tensor,
          intrinsics.federated_zip(
            [intrinsics.federated_value(10, placements.CLIENTS), 
            intrinsics.federated_value(10, placements.CLIENTS)])),
          0, add_numbers)

    result = _run_test_comp_produces_federated_value(self, comp, num_clients=3)
    self.assertEqual(result.numpy(), 60)

  
if __name__ == '__main__':
  absltest.main()

