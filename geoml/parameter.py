# geoML - machine learning models for geospatial data
# Copyright (C) 2019  Ítalo Gomes Gonçalves
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR a PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# __all__ = ["RealParameter",
#            "PositiveParameter",
#            "CompositionalParameter",
#            "CircularParameter"]

# import geoml.tftools as _tftools

import tensorflow as _tf
import numpy as _np
import pickle as _pickle


class Parametric(object):
    """An abstract class for objects with trainable parameters"""
    def __init__(self):
        self.parameters = {}
        self._all_parameters = []

    def pretty_print(self, depth=0):
        raise NotImplementedError()

    def __repr__(self):
        return self.pretty_print()

    @property
    def all_parameters(self):
        return self._all_parameters

    def _add_parameter(self, name, parameter):
        self.parameters[name] = parameter
        self._all_parameters.append(parameter)

    def _register(self, parametric):
        self._all_parameters.extend(parametric.all_parameters)
        return parametric

    def get_parameter_values(self, complete=False):
        value = []
        shape = []
        position = []
        min_val = []
        max_val = []

        for index, parameter in enumerate(self._all_parameters):
            if (not parameter.fixed) | complete:
                value.append(_tf.reshape(parameter.variable, [-1]).
                                 numpy())
                shape.append(_tf.shape(parameter.variable).numpy())
                position.append(index)
                min_val.append(_tf.reshape(parameter.min_transformed, [-1]).
                               numpy())
                max_val.append(_tf.reshape(parameter.max_transformed, [-1]).
                               numpy())

        min_val = _np.concatenate(min_val, axis=0)
        max_val = _np.concatenate(max_val, axis=0)
        value = _np.concatenate(value, axis=0)

        return value, shape, position, min_val, max_val

    def update_parameters(self, value, shape, position):
        sizes = _np.array([int(_np.prod(sh)) for sh in shape])
        value = _np.split(value, _np.cumsum(sizes))[:-1]
        value = [_np.squeeze(val) if len(sh) == 0 else val
                    for val, sh in zip(value, shape)]

        for val, sh, pos in zip(value, shape, position):
            self._all_parameters[pos].set_value(
                _np.reshape(val, sh) if len(sh) > 0 else val,
                transformed=True
            )

    def save_state(self, file):
        parameters = self.get_parameter_values(complete=True)
        with open(file, 'wb') as f:
            _pickle.dump(parameters, f)

    def load_state(self, file):
        with open(file, 'rb') as f:
            parameters = _pickle.load(f)

        value, shape, position, k_min_val, k_max_val = parameters
        self.update_parameters(value, shape, position)


class RealParameter(object):
    """
    Trainable model parameter. Can be a vector, matrix, or scalar.

    The `fixed` property applies to the array as a whole.
    """
    def __init__(self, value, min_val, max_val, fixed=False,
                 name="Parameter"):
        self.name = name
        self.fixed = fixed

        value = _np.array(value)
        min_val = _np.array(min_val)
        max_val = _np.array(max_val)

        if not max_val.shape == value.shape:
            raise ValueError(
                "Shape of max_val do not match shape of value: expected %s "
                "and found %s" % (str(value.shape),
                                  str(max_val.shape)))

        if not min_val.shape == value.shape:
            raise ValueError(
                "Shape of min_val do not match shape of value: expected %s "
                "and found %s" % (str(value.shape),
                                  str(min_val.shape)))

        self.shape = value.shape

        self.variable = _tf.Variable(self._transform(value),
                                     dtype=_tf.float64, name=name)

        self.max_transformed = _tf.Variable(
            self._transform(max_val), dtype=_tf.float64)
        self.min_transformed = _tf.Variable(
            self._transform(min_val), dtype=_tf.float64)

        self.refresh()

    def _transform(self, x):
        return x

    def _back_transform(self, x):
        return x

    def fix(self):
        self.fixed = True

    def unfix(self):
        self.fixed = False

    def set_limits(self, min_val=None, max_val=None):
        if min_val is not None:
            self.min_transformed.assign(self._transform(min_val))

        if max_val is not None:
            self.max_transformed.assign(self._transform(max_val))
        self.refresh()

    def set_value(self, value, transformed=False):
        if transformed:
            self.variable.assign(value)
        else:
            self.variable.assign(self._transform(value))
        self.refresh()

    def get_value(self):
        return self._back_transform(self.variable)

    def refresh(self):
        value = _tf.maximum(self.min_transformed,
                            _tf.minimum(self.max_transformed, self.variable))
        self.variable.assign(value)

    def randomize(self):
        val = (self.variable - self.min_transformed) \
              / (self.max_transformed - self.min_transformed)
        val = val + _np.random.uniform(size=self.shape, low=-0.05, high=0.05)
        val = _tf.maximum(0, _tf.minimum(1, val))
        val = val * (self.max_transformed - self.min_transformed) \
              + self.min_transformed
        self.variable.assign(val)


class PositiveParameter(RealParameter):
    """Parameter in log scale"""

    def _transform(self, x):
        return _tf.math.log(_tf.cast(x, _tf.float64))

    def _back_transform(self, x):
        return _tf.math.exp(x)


class CompositionalParameter(RealParameter):
    """
    A vector parameter in logit coordinates
    """
    def __init__(self, value, fixed=False, name="Parameter"):
        super().__init__(value, value, value, fixed, name=name)
        self.min_transformed.assign(-10 * _tf.ones_like(self.variable))
        self.max_transformed.assign(10 * _tf.ones_like(self.variable))
        self.variable.assign(self._transform(value))

    def _transform(self, x):
        x_tr = _tf.math.log(_tf.cast(x, _tf.float64))
        return x_tr - _tf.reduce_mean(x_tr)

    def _back_transform(self, x):
        return _tf.nn.softmax(x)


class CircularParameter(RealParameter):
    def refresh(self):
        amp = self.max_transformed - self.min_transformed
        n_laps = _tf.floor((self.variable - self.min_transformed) / amp)
        value = self.variable - n_laps * amp
        self.variable.assign(value)


class UnitColumnNormParameter(RealParameter):
    def __init__(self, value, min_val, max_val, fixed=False, name="Parameter"):
        value = _np.array(value)
        if len(value.shape) != 2:
            raise ValueError("value must be rank 2")
        super().__init__(value, min_val, max_val, fixed, name)

    def refresh(self):
        value = self.get_value()
        normalized = value / (_tf.math.reduce_euclidean_norm(
            value, axis=0, keepdims=True) + 1e-6)
        self.variable.assign(normalized)


class CenteredUnitColumnNormParameter(RealParameter):
    def __init__(self, value, min_val, max_val, fixed=False, name="Parameter"):
        value = _np.array(value)
        if len(value.shape) != 2:
            raise ValueError("value must be rank 2")
        super().__init__(value, min_val, max_val, fixed, name)

    def refresh(self):
        value = self.get_value()
        value = value - _tf.reduce_mean(value, axis=1, keepdims=True)
        normalized = value / (_tf.math.reduce_euclidean_norm(
            value, axis=0, keepdims=True) + 1e-6)
        self.variable.assign(normalized)


class UnitColumnSumParameter(RealParameter):
    def __init__(self, value, fixed=False, name="Parameter"):
        value = _np.array(value)
        if len(value.shape) != 2:
            raise ValueError("value must be rank 2")
        super().__init__(value, value, value, fixed, name)
        self.min_transformed.assign(-100 * _tf.ones_like(self.variable))
        self.max_transformed.assign(100 * _tf.ones_like(self.variable))
        self.variable.assign(self._transform(value))

    def _transform(self, x):
        x_tr = _tf.math.log(_tf.cast(x, _tf.float64))
        return x_tr - _tf.reduce_mean(x_tr, axis=0, keepdims=True)

    def _back_transform(self, x):
        return _tf.nn.softmax(x, axis=0)


class OrthonormalMatrix(RealParameter):
    def __init__(self, rows, cols, batch_shape=(),
                 fixed=False, name="Parameter"):
        if cols > rows:
            raise ValueError("cols cannot be higher than rows")
        # rnd = _tf.random.stateless_normal(batch_shape + (rows, cols),
        #                                   seed=[rows, cols])
        rnd = _tf.random.normal(batch_shape + (rows, cols))
        q, _ = _tf.linalg.qr(rnd)
        value = q.numpy()
        min_val = -1.1 * _np.ones_like(value)
        max_val = 1.1 * _np.ones_like(value)
        super().__init__(value, min_val, max_val, fixed, name)

    def refresh(self):
        value = self.get_value()
        norm = _tf.math.reduce_euclidean_norm(value, axis=0, keepdims=True)
        value = value / (norm + 1e-6)
        q, _ = _tf.linalg.qr(value)
        # q = q * norm
        self.variable.assign(q)


class CenteredOrthonormalMatrix(RealParameter):
    def __init__(self, rows, cols, batch_shape=(),
                 fixed=False, name="Parameter"):
        if cols > rows:
            raise ValueError("cols cannot be higher than rows")
        rnd = _tf.random.normal(batch_shape + (rows, cols))
        rnd = rnd - _tf.reduce_mean(rnd, axis=-2, keepdims=True)
        q, _ = _tf.linalg.qr(rnd)
        value = q.numpy()
        min_val = -1.1 * _np.ones_like(value)
        max_val = 1.1 * _np.ones_like(value)
        super().__init__(value, min_val, max_val, fixed, name)

    def refresh(self):
        value = self.get_value()
        value = value - _tf.reduce_mean(value, axis=-2, keepdims=True)
        norm = _tf.math.reduce_euclidean_norm(value, axis=0, keepdims=True)
        value = value / (norm + 1e-6)
        q, _ = _tf.linalg.qr(value)
        # q = q * norm
        self.variable.assign(q)
