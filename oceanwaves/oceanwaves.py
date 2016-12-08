import copy
import pyproj
import logging
import numpy as np
import xarray as xr
import scipy.integrate
import scipy.interpolate
from collections import OrderedDict

from .units import simplify
from .plot import OceanWavesPlotMethods
from .spectral import *


# initialize logger
logger = logging.getLogger(__name__)


class OceanWaves(xr.Dataset):
    '''Class to store (spectral) data of ocean waves

    The class is a specific variant of an xarray.Dataset that defines
    any selection of the following dimensions: time, location,
    frequency and direction. The dependent variable is some form of
    wave energy.

    The class has methods to compute spectral moments and derived wave
    properties, like the significant wave height and various spectral
    wave periods. In addition the peak wave period and peak wave
    directions can be computed using dedicated methods.

    The class automatically converts locations from a local coordinate
    reference system to lat/lon coordinates, if the local coordinate
    reference system is specified.

    The class interpretates combined variable units and simplifies the
    result to practical entities.

    The class provides two plotting routines: 1) plotting of spectral
    wave data in a raster of subplots and 2) plotting of spectral wabe
    data on a map.

    The class supports all convenient properties of an xarray.Dataset,
    like writing to netCDF or converting to pandas.DataFrame.

    TODO:

    * improve plotting routines

    * add phase functions to use with tides: phase estimates, phase
      interpolation, etc.

    '''


    crs = None
    extra_args = None
    

    def __init__(self, time=None, location=None, frequency=None,
                 direction=None, energy=None, time_units='s',
                 location_units='m', frequency_units='Hz',
                 direction_units='deg', energy_units='m^2/Hz',
                 attrs=None, crs=None, **kwargs):
        '''Initialize class

        Sets dimensions, converts coordinates and fills the dataset,
        if data is provided.

        Parameters
        ----------
        time : iterable, optional
            Time coordinates, each item can be a datetime object or
            float
        location : iterable of 2-tuples, optional
            Location coordinates, each item is a 2-tuple with x- and
            y-coordinates
        frequency : iterable, optional
            Frequency cooridinates
        direction : iterable, optional
            Direction coordinates
        energy : matrix, optional
            Wave energy
        time_units : str, optional
            Units of time coordinates (default: s)
        location_units : str, optional
            Units of location coordinates (default: m)
        frequency_units : str, optional
            Units of frequency coordinates (default: Hz)
        direction_units : str, optional
            Units of direction coordinates (default: deg)
        energy_units : str, optional
            Units of wave energy (default: m^2/Hz)
        attrs : dict-like, optional
            Global attributes
        crs : str, optional
            Proj4 specification of local coordinate reference system
        kwargs : dict, optional
            Additional options passed to the xarray.Dataset
            initialization method

        See Also
        --------
        oceanwaves.OceanWaves.reinitialize

        '''

        self.extra_args = kwargs
        
        coords = OrderedDict()
        data_vars = OrderedDict()

        # simplify dimensions
        time = np.asarray(time)
        location = np.asarray(location)
        frequency = np.asarray(frequency, dtype=np.float)
        direction = np.asarray(direction, dtype=np.float)
        energy = np.asarray(energy, dtype=np.float)
        
        # simplify units
        time_units = simplify(time_units)
        location_units = simplify(location_units)
        frequency_units = simplify(frequency_units)
        direction_units = simplify(direction_units)
        energy_units = simplify(energy_units)
        
        # determine object dimensions
        if self._isvalid(time):
            coords['time']      = xr.Variable('time',
                                              time,
                                              attrs=dict(units=time_units))

        if self._isvalid(location):
            coords['location']  = xr.Variable('location',
                                              np.arange(len(location)))
            
            x, y = zip(*location)
            data_vars['x']      = xr.Variable('location',
                                              np.asarray(x),
                                              attrs=dict(units=location_units))
            data_vars['y']      = xr.Variable('location',
                                              np.asarray(y),
                                              attrs=dict(units=location_units))
                
            data_vars['lat']    = xr.Variable('location',
                                              np.asarray(x) + np.nan,
                                              attrs=dict(units='degN'))
            data_vars['lon']    = xr.Variable('location',
                                              np.asarray(y) + np.nan,
                                              attrs=dict(units='degE'))

        if self._isvalid(frequency, mask=frequency>0):
            coords['frequency'] = xr.Variable('frequency',
                                              frequency[frequency>0],
                                              attrs=dict(units=frequency_units))
            
        if self._isvalid(direction):
            coords['direction'] = xr.Variable('direction',
                                               direction,
                                               attrs=dict(units=direction_units))

        # determine object shape
        shp = tuple([len(c) for c in coords.itervalues()])

        # initialize energy variable
        data_vars['energy']     = xr.DataArray(np.nan + np.zeros(shp),
                                               dims=coords,
                                               coords=coords,
                                               attrs=dict(units=energy_units))
        
        # initialize empty object
        super(OceanWaves, self).__init__(data_vars=data_vars,
                                         coords=coords,
                                         attrs=attrs,
                                         **kwargs)

        # set wave energy
        if self._isvalid(energy):
            self.energy = energy

        # convert coordinates
        self.convert_coordinates(crs)
        

    def Hm0(self, f_min=0, f_max=np.inf):
        '''Compute significant wave height based on zeroth order moment

        Parameters
        ----------
        f_min : float
            Minimum frequency to include in moment
        f_max : float
            Maximum frequency to include in moment

        Returns
        -------
        H : xarray.DataArray
            Significant wave height at each point in time and location
            in the dataset

        '''

        # compute moments
        m0 = self.moment(0, f_min=f_min, f_max=f_max)

        # compute wave height
        H = 4. * np.sqrt(m0)

        # determine units
        units = '(%s)^0.5' % m0.attrs['units']
        H.attrs['units'] = simplify(units)

        return H

    
    def Tm01(self):
        '''Compute wave period based on first order moment

        Returns
        -------
        T : xarray.DataArray
            Spectral wave period at each point in time and location in
            the dataset

        '''
    
        # compute moments
        m0 = self.moment(0)
        m1 = self.moment(1)

        # compute wave period
        T = m0/m1

        # determine units
        units = '(%s)/(%s)' % (m0.attrs['units'], m1.attrs['units'])
        T.attrs['units'] = simplify(units)

        return T


    def Tm02(self):
        '''Compute wave period based on second order moment

        Returns
        -------
        T : xarray.DataArray
            Spectral wave period at each point in time and location in
            the dataset

        '''

        # compute moments
        m0 = self.moment(0)
        m2 = self.moment(2)

        # compute wave period
        T = np.sqrt(m0/m2)

        # determine units
        units = '((%s)/(%s))^0.5' % (m0.attrs['units'], m2.attrs['units'])
        T.attrs['units'] = simplify(units)

        return T


    def Tp(self):
        '''Alias for :meth:`oceanwaves.OceanWaves.peak_period`

        '''

        return self.peak_period()

    
    def peak_period(self):
        '''Compute peak wave period
        
        Returns
        -------
        T : xarray.DataArray
            Peak wave period at each point in time and location in the
            dataset

        '''
    
        if self.has_dimension('frequency', raise_error=True):

            coords = OrderedDict(self.coords)
            E = self.variables['energy']

            # determine peak frequencies
            if self.has_dimension('direction'):
                coords.pop('direction')
                E = E.max(dim='direction')

            # determine peak directions
            f = coords.pop('frequency').values
            ix = E.argmax(dim='frequency').values
            peaks = 1. / f[ix.flatten()].reshape(ix.shape)

            # determine units
            units = '1/(%s)' % self.variables['frequency'].attrs['units']
            units = simplify(units)
            
            return xr.DataArray(peaks, coords=coords, attrs=dict(units=units))

        
    def peak_direction(self):
        '''Compute peak wave direction

        Returns
        -------
        theta : xarray.DataArray
            Peak wave direction at each point in time and location in
            the dataset

        '''

        if self.has_dimension('direction', raise_error=True):

            coords = OrderedDict(self.coords)
            E = self.variables['energy']

            # determine peak frequencies
            if self.has_dimension('frequency'):
                coords.pop('frequency')
                E = E.max(dim='frequency')

            # determine peak directions
            theta = coords.pop('direction').values
            ix = E.argmax(dim='direction').values
            peaks = theta[ix.flatten()].reshape(ix.shape)

            # determine units
            units = self.variables['direction'].attrs['units']
            units = simplify(units)
            
            return xr.DataArray(peaks, coords=coords, attrs=dict(units=units))
            

    def moment(self, n, f_min=0., f_max=np.inf):
        '''Compute nth order moment of wave spectrum

        Parameters
        ----------
        n : int
            Order of moment
        f_min : float
            Minimum frequency to include in moment
        f_max : float
            Maximum frequency to include in moment

        Returns
        -------
        m : xarray.DataArray
            nth order moment of the wave spectrum at each point in
            time and location in the dataset

        '''

        if self.has_dimension('frequency', raise_error=True):

            coords = OrderedDict(self.coords)
            E = self.variables['energy'].values
        
            # integrate directions
            if self.has_dimension('direction'):
                theta = coords.pop('direction').values
                E = np.abs(np.trapz(E, theta, axis=-1))

            # integrate frequencies
            f = coords.pop('frequency').values
            if f_min == 0. and f_max == np.inf:
                
                m = np.trapz(E * f**n, f, axis=-1)
                
            else:

                if n != 0:
                    logger.warn('Computing %d-order moment using a frequency range; Are you sure what you are doing?', n)
                    
                # integrate range of frequencies
                f_min = np.maximum(f_min, np.min(f))
                f_max = np.minimum(f_max, np.max(f))
                
                m = scipy.integrate.cumtrapz(E * f**n, f, axis=-1, initial=0)

                dims = []
                if self.has_dimension('time'):
                    dims.append(coords['time'].values.flatten().astype(np.float))
                if self.has_dimension('location'):
                    dims.append(coords['location'].values.flatten().astype(np.float))
                    
                points = tuple(dims + [f.flatten()])
                
                xi_min = zip(*[x.flatten() for x in np.meshgrid(*(dims + [f_min]))])
                xi_max = zip(*[x.flatten() for x in np.meshgrid(*(dims + [f_max]))])

                m_min = scipy.interpolate.interpn(points, m, xi_min)
                m_max = scipy.interpolate.interpn(points, m, xi_max)
                
                m = (m_max - m_min).reshape([len(x) for x in dims])

            # determine units
            E_units = self.variables['energy'].attrs['units']
            f_units = self.variables['frequency'].attrs['units']
            units = E_units + ('*((%s)^%d)' % (f_units, n+1))
            units = simplify(units)
            
            return xr.DataArray(m, dims=coords, coords=coords,
                                attrs=dict(units=units))


    def to_spectral(self, frequency, frequency_units='Hz', Tp=4.,
                    gamma=3.3, sigma_low=.07, sigma_high=.09,
                    shape='jonswap', method='yamaguchi', g=9.81,
                    normalize=True):
        '''Convert wave energy to spectrum

        Spreads total wave energy over a given set of frequencies
        according to the JONSWAP spectrum shape.

        See :func:`oceanwaves.spectral.jonswap` for options.

        Returns
        -------
        OceanWaves
            New OceanWaves object

        '''

        if self.has_dimension('frequency'):
            return self

        frequency = frequency[frequency>0]

        energy = self.variables['energy'].values
        energy_units = self.variables['energy'].attrs['units']

        # convert to energy
        if self.units == 'm':
            energy **= 2.
            energy_units = '(%s)^2' % energy_units
            
        # expand energy matrix
        if self.has_dimension('direction'):
            energy = energy[...,np.newaxis,:].repeat(len(frequency), axis=-2)
        else:
            energy = energy[...,np.newaxis].repeat(len(frequency), axis=-1)

        # compute spectrum shape
        if shape.lower() == 'jonswap':
            spectrum = jonswap(frequency, Hm0=1., Tp=Tp, gamma=gamma,
                               sigma_low=sigma_low,
                               sigma_high=sigma_high, g=g,
                               method=method, normalize=normalize)
        else:
            raise ValueError('Unknown spectrum shape: %s', shape)
        
        for n in energy.shape[::-1][1:]:
            spectrum = spectrum[np.newaxis,...].repeat(n, axis=0)

        energy = np.multiply(energy, spectrum)

        # determine units
        units = '(%s)/(%s)' % (energy_units,
                               frequency_units)

        # reinitialize object with new dimensions
        return self.reinitialize(frequency=frequency,
                                 frequency_units=frequency_units,
                                 energy=energy)


    def to_directional(self, direction, direction_units='deg',
                       theta_peak=0., s=20., normalize=True):
        '''Convert omnidirectional spectrum to a directional spectrum

        Spreads total wave energy over a given set of directions
        according to a spreading factor ``s``.

        See :func:`oceanwaves.spectral.directional_spreading` for options.

        Returns
        -------
        OceanWaves
            New OceanWaves object

        '''

        if self.has_dimension('direction'):
            return self

        # expand energy matrix
        energy = self.variables['energy'].values
        energy = energy[...,np.newaxis].repeat(len(direction), axis=-1)

        # compute directional spreading
        spreading = directional_spreading(direction,
                                          units=direction_units,
                                          theta_peak=theta_peak, s=s,
                                          normalize=normalize)
        for n in energy.shape[::-1][1:]:
            spreading = spreading[np.newaxis,...].repeat(n, axis=0)

        energy = np.multiply(energy, spreading)

        # determine units
        units = '(%s)/(%s)' % (self.variables['energy'].attrs['units'],
                               direction_units)

        # reinitialize object with new dimensions
        return self.reinitialize(direction=direction,
                                 direction_units=direction_units,
                                 energy=energy,
                                 energy_units=simplify(units))


    def to_omnidirectional(self):
        '''Convert directional spectrum to an omnidirectional spectrum

        Integrate spectral energy over the directions.

        Returns
        -------
        OceanWaves
            New OceanWaves object

        '''

        if not self.has_dimension('direction'):
            return self

        # expand energy matrix
        energy = np.trapz(self.variables['energy'].values,
                          self.coords['direction'].values, axis=-1)

        # determine units
        units = '(%s)*(%s)' % (self.variables['energy'].attrs['units'],
                               self.variables['direction'].attrs['units'])
        
        # reinitialize object with new dimensions
        return self.reinitialize(direction=None,
                                 energy=energy,
                                 energy_units=simplify(units))


    def to_radians(self):
        '''Convert directions to radians'''

        if self.has_dimension('direction'):
            d = self.coords['direction']
            if d.attrs['units'].lower().startswith('deg'):
                return self.reinitialize(direction=np.radians(d.values),
                                         direction_units='rad')

        return self
    

    def to_degrees(self):
        '''Convert directions to degrees'''

        if self.has_dimension('direction'):
            d = self.coords['direction']
            if d.attrs['units'].lower().startswith('rad'):
                return self.reinitialize(direction=np.degrees(d.values),
                                         direction_units='deg')

        return self


    def reinitialize(self, **kwargs):
        '''Reinitializes current object with modified parameters

        Gathers current object's initialization settings and updates
        them with the given initialization options. Then initializes a
        new object with the resulting option set. See for all
        supported options the initialization method of this class.

        Parameters
        ----------
        kwargs : dict
            Keyword/value pairs with initialization options that need
            to be overwritten

        Returns
        -------
        OceanWaves
            New OceanWaves object

        '''

        settings = dict(attrs = self.attrs,
                        crs = self.crs)

        if self.has_dimension('direction'):
            settings['direction'] = self.coords['direction'].values
            settings['direction_units'] = self.coords['direction'].attrs['units']
            
        if self.has_dimension('frequency'):
            settings['frequency'] = self.coords['frequency'].values
            settings['frequency_units'] = self.coords['frequency'].attrs['units']

        if self.has_dimension('location'):
            x = self.variables['x'].values
            y = self.variables['y'].values
            settings['location'] = zip(x, y)
            settings['location_units'] = self.variables['x'].attrs['units']
            
        if self.has_dimension('time'):
            settings['time'] = self.coords['time'].values
            settings['time_units'] = self.coords['time'].attrs['units']

        settings['energy'] = self.variables['energy'].values

        if type(self.extra_args) is dict:
            settings.update(self.extra_args)
        
        settings.update(**kwargs)

        return OceanWaves(**settings)

    
    @property
    def plot(self):

        obj = self.to_radians()

        if self.has_dimension('location'):
            return OceanWavesPlotMethods(obj.data_vars['energy'],
                                         obj.variables['x'].values,
                                         obj.variables['y'].values)
        else:
            return OceanWavesPlotMethods(obj.data_vars['energy'])
    
        
    @property
    def energy(self):

        return self.data_vars['energy']

    
    @energy.setter
    def energy(self, energy):
        '''Convenience function to set wave energy with arbitrary dimension order

        '''

        if len(self.shape) < len(energy.shape):
            energy = np.squeeze(energy)
        if len(self.shape) != len(energy.shape):
            raise ValueError('Incompatible number of dimensions in energy matrix: '
                             '%s, while %s was expected' % (energy.shape, self.shape))
        elif self.shape != energy.shape:
            if ~all([x in energy.shape for x in self.shape]) or \
               ~all([x in self.shape for x in energy.shape]):
                raise ValueError('Incompatible shape of energy matrix: '
                                 '%s, while %s was expected' % (energy.shape, self.shape))
            else:
                raise ValueError('Wrong order of dimensions in energy matrix: '
                                 '%s, while %s was expected' % (energy.shape, self.shape)) # TODO: fix this automatically

        self.variables['energy'].values = energy

        
    @property
    def shape(self):

        return self.variables['energy'].shape


    @property
    def units(self):

        return self.variables['energy'].attrs['units']


    def has_dimension(self, dim, raise_error=False):
        '''Checks if dimension is present

        Parameters
        ----------
        dim : str
            Name of dimension
        raise_error : bool, optional
            Raise error if dimension is absent (default: False)

        Returns
        -------
        bool
            Boolean indicating whether dimension is present

        Raises
        ------
        ValueError

        '''

        if dim in self.dims.keys():

            if len(self.variables[dim].values) > 1:

                return True

            elif raise_error:

                raise ValueError('Object has dimension "%s", but it has a length unity' % dim)

        elif raise_error:

            raise ValueError('Object has no dimension "%s"' % dim)

        return False


    def convert_coordinates(self, crs):
        '''Convert coordinates from local coordinate reference system to lat/lon

        Parameters
        ----------
        crs : str
            Proj4 specification of local coordinate reference system

        '''

        if self.has_dimension('location'):
            
            self.crs = crs

            if crs is not None:
                p1 = pyproj.Proj(init=crs)
                p2 = pyproj.Proj(proj='latlong', datum='WGS84')
                x = self._variables['x'].values
                y = self._variables['y'].values
                lat, lon = pyproj.transform(p1, p2, x, y)
                self.variables['lat'].values = lat
                self.variables['lon'].values = lon


    @staticmethod
    def _isvalid(arr, mask=None):

        # check if not None
        if arr is None:
            return False

        # check if iterable
        try:
            itr = iter(arr)
        except TypeError:
            return False

        # apply mask
        if mask is not None:
            arr = arr[mask]

        # check if non-zero
        if len(arr) == 0:
            return False

        # check if all invalid
        if arr.dtype == 'float':
            if ~np.any(np.isfinite(arr)):
                return False

        return True
