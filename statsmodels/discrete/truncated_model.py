from __future__ import division

__all__ = ["TruncatedPoisson", "TruncatedNegativeBinomialP", "Hurdle"]

import numpy as np
import statsmodels.base.model as base
import statsmodels.base.wrapper as wrap
import statsmodels.regression.linear_model as lm
from statsmodels.distributions.discrete import (
    truncatedpoisson,
    truncatednegbin,
    )
from statsmodels.discrete.discrete_model import (
    DiscreteModel,
    CountModel,
    CountResults,
    L1CountResults,
    Poisson,
    NegativeBinomialP,
    GeneralizedPoisson,
    _discrete_results_docs,
    )
from statsmodels.tools.numdiff import approx_hess
from statsmodels.tools.decorators import cache_readonly
from copy import deepcopy


class GenericTruncated(CountModel):
    __doc__ = """
    Generic Truncated model for count data

    %(params)s
    %(extra_params)s

    Attributes
    -----------
    endog : array
        A reference to the endogenous response variable
    exog : array
        A reference to the exogenous design.
    truncation : int, optional
        Truncation parameter specify truncation point out of the support
        of the distribution. pmf(k) = 0 for k <= truncation
    """ % {'params': base._model_params_doc,
           'extra_params':
           """offset : array_like
        Offset is added to the linear prediction with coefficient equal to 1.
    exposure : array_like
        Log(exposure) is added to the linear prediction with coefficient
        equal to 1.

    """ + base._missing_param_doc}

    def __init__(self, endog, exog, truncation=0, offset=None,
                 exposure=None, missing='none', **kwargs):
        super(GenericTruncated, self).__init__(
            endog,
            exog,
            offset=offset,
            exposure=exposure,
            missing=missing,
            **kwargs
            )
        self.exog = self.exog[self.endog >= (truncation + 1)]
        self.endog = self.endog[self.endog >= (truncation + 1)]
        self.trunc = truncation
        self.truncation = truncation  # needed for recreating model
        self._init_keys.extend(['truncation'])
        self._null_drop_keys = []

    def loglike(self, params):
        """
        Loglikelihood of Generic Truncated model

        Parameters
        ----------
        params : array-like
            The parameters of the model.

        Returns
        -------
        loglike : float
            The log-likelihood function of the model evaluated at `params`.
            See notes.

        Notes
        --------

        """
        return np.sum(self.loglikeobs(params))

    def loglikeobs(self, params):
        """
        Loglikelihood for observations of Generic Truncated model

        Parameters
        ----------
        params : array-like
            The parameters of the model.

        Returns
        -------
        loglike : ndarray (nobs,)
            The log likelihood for each observation of the model evaluated
            at `params`. See Notes

        Notes
        --------

        """
        llf_main = self.model_main.loglikeobs(params)

        pmf = np.zeros_like(self.endog, dtype=np.float64)
        for i in range(self.trunc + 1):
            model = self.model_main.__class__(np.ones_like(self.endog) * i,
                                              self.exog)
            pmf += np.exp(model.loglikeobs(params))

        llf = llf_main - np.log(1 - pmf)

        return llf

    def score_obs(self, params):
        """
        Generic Truncated model score (gradient) vector of the log-likelihood

        Parameters
        ----------
        params : array-like
            The parameters of the model

        Returns
        -------
        score : ndarray, 1-D
            The score vector of the model, i.e. the first derivative of the
            loglikelihood function, evaluated at `params`
        """
        score_main = self.model_main.score_obs(params)

        pmf = np.zeros_like(self.endog, dtype=np.float64)
        score_trunc = np.zeros_like(score_main, dtype=np.float64)
        for i in range(self.trunc + 1):
            model = self.model_main.__class__(np.ones_like(self.endog) * i,
                                              self.exog)
            pmf_i = np.exp(model.loglikeobs(params))
            score_trunc += (model.score_obs(params).T * pmf_i).T
            pmf += pmf_i

        dparams = score_main + (score_trunc.T / (1 - pmf)).T

        return dparams

    def score(self, params):
        """
        Generic Truncated model score (gradient) vector of the log-likelihood

        Parameters
        ----------
        params : array-like
            The parameters of the model

        Returns
        -------
        score : ndarray, 1-D
            The score vector of the model, i.e. the first derivative of the
            loglikelihood function, evaluated at `params`
        """
        return self.score_obs(params).sum(0)

    def fit(self, start_params=None, method='bfgs', maxiter=35,
            full_output=1, disp=1, callback=None,
            cov_type='nonrobust', cov_kwds=None, use_t=None, **kwargs):
        if start_params is None:
            offset = getattr(self, "offset", 0) + getattr(self, "exposure", 0)
            if np.size(offset) == 1 and offset == 0:
                offset = None
            model = self.model_main.__class__(self.endog, self.exog,
                                              offset=offset)
            start_params = model.fit(disp=0).params
        mlefit = super(GenericTruncated, self).fit(
            start_params=start_params,
            method=method,
            maxiter=maxiter,
            disp=disp,
            full_output=full_output,
            callback=lambda x: x,
            **kwargs
            )

        zipfit = self.result(self, mlefit._results)
        result = self.result_wrapper(zipfit)

        if cov_kwds is None:
            cov_kwds = {}

        result._get_robustcov_results(cov_type=cov_type,
                                      use_self=True, use_t=use_t, **cov_kwds)
        return result

    fit.__doc__ = DiscreteModel.fit.__doc__

    def fit_regularized(
            self, start_params=None, method='l1',
            maxiter='defined_by_method', full_output=1, disp=1, callback=None,
            alpha=0, trim_mode='auto', auto_trim_tol=0.01, size_trim_tol=1e-4,
            qc_tol=0.03, **kwargs):

        if np.size(alpha) == 1 and alpha != 0:
            k_params = self.exog.shape[1]
            alpha = alpha * np.ones(k_params)

        alpha_p = alpha
        if start_params is None:
            offset = getattr(self, "offset", 0) + getattr(self, "exposure", 0)
            if np.size(offset) == 1 and offset == 0:
                offset = None
            model = self.model_main.__class__(self.endog, self.exog,
                                              offset=offset)
            start_params = model.fit_regularized(
                start_params=start_params, method=method, maxiter=maxiter,
                full_output=full_output, disp=0, callback=callback,
                alpha=alpha_p, trim_mode=trim_mode,
                auto_trim_tol=auto_trim_tol,
                size_trim_tol=size_trim_tol, qc_tol=qc_tol, **kwargs).params
        cntfit = super(CountModel, self).fit_regularized(
                start_params=start_params, method=method, maxiter=maxiter,
                full_output=full_output, disp=disp, callback=callback,
                alpha=alpha, trim_mode=trim_mode, auto_trim_tol=auto_trim_tol,
                size_trim_tol=size_trim_tol, qc_tol=qc_tol, **kwargs)

        if method in ['l1', 'l1_cvxopt_cp']:
            discretefit = self.result_reg(self, cntfit)
        else:
            raise TypeError(
                    "argument method == %s, which is not handled" % method)

        return self.result_reg_wrapper(discretefit)

    fit_regularized.__doc__ = DiscreteModel.fit_regularized.__doc__

    def hessian(self, params):
        """
        Generic Truncated model Hessian matrix of the loglikelihood

        Parameters
        ----------
        params : array-like
            The parameters of the model

        Returns
        -------
        hess : ndarray, (k_vars, k_vars)
            The Hessian, second derivative of loglikelihood function,
            evaluated at `params`

        Notes
        -----
        """
        return approx_hess(params, self.loglike)


class TruncatedPoisson(GenericTruncated):
    """
    Truncated Poisson model for count data

    %(params)s
    %(extra_params)s

    Attributes
    -----------
    endog : array
        A reference to the endogenous response variable
    exog : array
        A reference to the exogenous design.
    truncation : int, optional
        Truncation parameter specify truncation point out of the support
        of the distribution. pmf(k) = 0 for k <= truncation
    """ % {'params': base._model_params_doc,
           'extra_params':
           """offset : array_like
        Offset is added to the linear prediction with coefficient equal to 1.
    exposure : array_like
        Log(exposure) is added to the linear prediction with coefficient
        equal to 1.

    """ + base._missing_param_doc}

    def __init__(self, endog, exog, offset=None, exposure=None,
                 truncation=0, missing='none', **kwargs):
        super(TruncatedPoisson, self).__init__(
            endog,
            exog,
            offset=offset,
            exposure=exposure,
            truncation=truncation,
            missing=missing,
            **kwargs
            )
        self.model_main = Poisson(self.endog, self.exog,
                                  exposure=exposure,
                                  offset=offset)
        self.model_dist = truncatedpoisson
        self.result = TruncatedPoissonResults
        self.result_wrapper = GenericTruncatedResultsWrapper
        self.result_reg = L1GenericTruncatedResults
        self.result_reg_wrapper = L1GenericTruncatedResultsWrapper

    def predict(self, params, exog=None, exposure=None, offset=None,
                which='mean', count_prob=None):
        """
        Paramaters
        ----------
        count_prob : array-like or int
            The counts for which you want the probabilities. If count_prob is
            None then the probabilities for each count from 0 to max(y) are
            given.

        Predict response variable of a count model given exogenous variables.
        Notes
        -----
        If exposure is specified, then it will be logged by the method.
        The user does not need to log it first.
        """

        exog, offset, exposure = self._get_predict_arrays(
            exog=exog,
            offset=offset,
            exposure=exposure
            )

        fitted = np.dot(exog, params[:exog.shape[1]])
        linpred = fitted + exposure + offset

        if which == 'mean':
            mu = np.exp(linpred)
            if self.truncation == 0:
                return mu / (1 - np.exp(-np.exp(linpred)))
            elif self.truncation == -1:
                return mu
            elif self.truncation > 0:
                counts = np.atleast_2d(np.arange(0, self.truncation + 1))
                # next is same as in prob-main below
                probs = self.model_main.predict(
                    params, exog=exog, exposure=np.exp(exposure),
                    offset=offset, which="prob", y_values=counts)
                prob_tregion = probs.sum(1)
                mean_tregion = (np.arange(self.truncation + 1) * probs).sum(1)
                mean = (mu - mean_tregion) / (1 - prob_tregion)
                return mean
        elif which == 'linear':
            return linpred
        elif which == 'mean-main':
            return np.exp(linpred)
        elif which == 'prob':
            if count_prob is not None:
                counts = np.atleast_2d(count_prob)
            else:
                counts = np.atleast_2d(np.arange(0, np.max(self.endog)+1))
            mu = self.predict(params, exog=exog, exposure=np.exp(exposure),
                              offset=offset, which="mean-main")[:, None]
            return self.model_dist.pmf(counts, mu, self.trunc)
        elif which == 'prob-main':
            if count_prob is not None:
                counts = np.atleast_2d(count_prob)
            else:
                counts = np.atleast_2d(np.arange(0, np.max(self.endog)+1))
            probs = self.model_main.predict(
                params, exog=exog, exposure=np.exp(exposure),
                offset=offset, which="prob")[:, None]
            return probs
        elif which == 'var':
            mu = np.exp(linpred)
            counts = np.atleast_2d(np.arange(0, self.truncation + 1))
            # next is same as in prob-main below
            probs = self.model_main.predict(
                params, exog=exog, exposure=np.exp(exposure),
                offset=offset, which="prob", y_values=counts)
            prob_tregion = probs.sum(1)
            mean_tregion = (np.arange(self.truncation + 1) * probs).sum(1)
            mean = (mu - mean_tregion) / (1 - prob_tregion)
            mnc2_tregion = (np.arange(self.truncation + 1)**2 *
                            probs).sum(1)
            mnc2 = (mu**2 + mu - mnc2_tregion) / (1 - prob_tregion)
            v = mnc2 - mean**2
            return v
        else:
            raise TypeError(
                "argument wich == %s not handled" % which)


class TruncatedNegativeBinomialP(GenericTruncated):
    """
    Truncated Generalized Negative Binomial model for count data

    %(params)s
    %(extra_params)s

    Attributes
    -----------
    endog : array
        A reference to the endogenous response variable
    exog : array
        A reference to the exogenous design.
    truncation : int, optional
        Truncation parameter specify truncation point out of the support
        of the distribution. pmf(k) = 0 for k <= truncation
    """ % {'params': base._model_params_doc,
           'extra_params':
           """offset : array_like
        Offset is added to the linear prediction with coefficient equal to 1.
    exposure : array_like
        Log(exposure) is added to the linear prediction with coefficient
        equal to 1.

    """ + base._missing_param_doc}

    def __init__(self, endog, exog, offset=None, exposure=None,
                 truncation=0, p=2, missing='none', **kwargs):
        super(TruncatedNegativeBinomialP, self).__init__(
            endog,
            exog,
            offset=offset,
            exposure=exposure,
            truncation=truncation,
            missing=missing,
            **kwargs
            )
        self.model_main = NegativeBinomialP(self.endog, self.exog,
                                            exposure=exposure,
                                            offset=offset, p=p)
        self.k_extra = self.model_main.k_extra
        self.exog_names.extend(self.model_main.exog_names[-self.k_extra:])
        self.model_dist = truncatednegbin
        self.result = TruncatedNegativeBinomialResults
        self.result_wrapper = GenericTruncatedResultsWrapper
        self.result_reg = L1GenericTruncatedResults
        self.result_reg_wrapper = L1GenericTruncatedResultsWrapper

    def predict(self, params, exog=None, exposure=None, offset=None,
                which='mean', count_prob=None):
        """
        Paramaters
        ----------
        count_prob : array-like or int
            The counts for which you want the probabilities. If count_prob is
            None then the probabilities for each count from 0 to max(y) are
            given.

        Predict response variable of a count model given exogenous variables.
        Notes
        -----
        If exposure is specified, then it will be logged by the method.
        The user does not need to log it first.
        """
        exog, offset, exposure = self._get_predict_arrays(
            exog=exog,
            offset=offset,
            exposure=exposure
            )

        fitted = np.dot(exog, params[:exog.shape[1]])
        linpred = fitted + exposure + offset
        alpha = params[-1]

        if which == 'mean':
            mu = np.exp(linpred)
            if self.truncation == 0:
                p = self.model_main.parameterization
                prob_zero = (1 + alpha * mu**(p-1))**(- 1 / alpha)
                return mu / (1 - prob_zero)
            elif self.truncation == -1:
                return mu
            elif self.truncation > 0:
                counts = np.atleast_2d(np.arange(0, self.truncation + 1))
                # next is same as in prob-main below
                probs = self.model_main.predict(
                    params, exog=exog, exposure=np.exp(exposure),
                    offset=offset, which="prob", y_values=counts)
                prob_tregion = probs.sum(1)
                mean_tregion = (np.arange(self.truncation + 1) * probs).sum(1)
                mean = (mu - mean_tregion) / (1 - prob_tregion)
                return mean
        elif which == 'linear':
            return linpred
        elif which == 'mean-main':
            return np.exp(linpred)
        elif which == 'prob':
            if count_prob is not None:
                counts = np.atleast_2d(count_prob)
            else:
                counts = np.atleast_2d(np.arange(0, np.max(self.endog)+1))
            mu = self.predict(params, exog=exog, exposure=np.exp(exposure),
                              offset=offset, which="mean-main")[:, None]
            p = self.model_main.parameterization
            return self.model_dist.pmf(counts, mu, params[-1], p, self.trunc)
        elif which == 'prob-main':
            if count_prob is not None:
                counts = np.atleast_2d(count_prob)
            else:
                counts = np.atleast_2d(np.arange(0, np.max(self.endog)+1))
            probs = self.model_main.predict(
                params, exog=exog, exposure=np.exp(exposure),
                offset=offset, which="prob", y_values=counts)[:, None]
            return probs
        elif which == 'var':
            mu = np.exp(linpred)
            counts = np.atleast_2d(np.arange(0, self.truncation + 1))
            # next is same as in prob-main below
            probs = self.model_main.predict(
                params, exog=exog, exposure=np.exp(exposure),
                offset=offset, which="prob", y_values=counts)
            prob_tregion = probs.sum(1)
            mean_tregion = (np.arange(self.truncation + 1) * probs).sum(1)
            mean = (mu - mean_tregion) / (1 - prob_tregion)
            mnc2_tregion = (np.arange(self.truncation + 1)**2 *
                            probs).sum(1)
            p = self.model_main.parameterization
            vm = mu * (1 + alpha * mu**(p-1))
            # uncentered 2nd moment
            mnc2 = (mu**2 + vm - mnc2_tregion) / (1 - prob_tregion)
            v = mnc2 - mean**2
            return v
        else:
            raise TypeError(
                "argument wich == %s not handled" % which)


class TruncatedGeneralizedPoisson(GenericTruncated):
    """
    Truncated Generalized Poisson model for count data

    %(params)s
    %(extra_params)s

    Attributes
    -----------
    endog : array
        A reference to the endogenous response variable
    exog : array
        A reference to the exogenous design.
    truncation : int, optional
        Truncation parameter specify truncation point out of the support
        of the distribution. pmf(k) = 0 for k <= truncation
    """ % {'params': base._model_params_doc,
           'extra_params':
           """offset : array_like
        Offset is added to the linear prediction with coefficient equal to 1.
    exposure : array_like
        Log(exposure) is added to the linear prediction with coefficient
        equal to 1.

    """ + base._missing_param_doc}

    def __init__(self, endog, exog, offset=None, exposure=None,
                 truncation=0, p=2, missing='none', **kwargs):
        super(TruncatedGeneralizedPoisson, self).__init__(
            endog,
            exog,
            offset=offset,
            exposure=exposure,
            truncation=truncation,
            missing=missing,
            **kwargs
            )
        self.model_main = GeneralizedPoisson(self.endog,
                                             self.exog,
                                             exposure=exposure,
                                             offset=offset,
                                             p=p)
        self.k_extra = self.model_main.k_extra
        self.exog_names.extend(self.model_main.exog_names[-self.k_extra:])
        self.model_dist = None
        self.result = TruncatedNegativeBinomialResults
        self.result_wrapper = GenericTruncatedResultsWrapper
        self.result_reg = L1GenericTruncatedResults
        self.result_reg_wrapper = L1GenericTruncatedResultsWrapper

    def predict(self, params, exog=None, exposure=None, offset=None,
                which='mean', count_prob=None):
        """
        Paramaters
        ----------
        count_prob : array-like or int
            The counts for which you want the probabilities. If count_prob is
            None then the probabilities for each count from 0 to max(y) are
            given.

        Predict response variable of a count model given exogenous variables.
        Notes
        -----
        If exposure is specified, then it will be logged by the method.
        The user does not need to log it first.
        """
        if exog is None:
            exog = self.exog

        if exposure is None:
            exposure = getattr(self, 'exposure', 0)
        elif exposure != 0:
            exposure = np.log(exposure)

        if offset is None:
            offset = getattr(self, 'offset', 0)

        fitted = np.dot(exog, params[:exog.shape[1]])
        linpred = fitted + exposure + offset

        if which == 'mean':
            if self.truncation == 0:
                return np.exp(linpred) / (1 - np.exp(-np.exp(linpred)))
            elif self.truncation == -1:
                return np.exp(linpred)
            elif self.truncation > 0:
                raise NotImplementedError("conditional mean not implemented")
        elif which == 'linear':
            return linpred
        elif which == 'mean-main':
            return np.exp(linpred)
        elif which == 'prob':
            if count_prob is not None:
                counts = np.atleast_2d(count_prob)
            else:
                counts = np.atleast_2d(np.arange(0, np.max(self.endog)+1))
            mu = self.predict(params, exog=exog, exposure=exposure,
                              offset=offset, which="mean-main")[:, None]
            p = self.model_main.parametrization
            return self.model_dist.pmf(counts, mu, params[-1], p, self.trunc)
        else:
            raise TypeError(
                "argument wich == %s not handled" % which)


class GenericCensored(CountModel):
    __doc__ = """
    Generic Censored model for count data

    %(params)s
    %(extra_params)s

    Attributes
    -----------
    endog : array
        A reference to the endogenous response variable
    exog : array
        A reference to the exogenous design.
    """ % {'params': base._model_params_doc,
           'extra_params':
           """offset : array_like
        Offset is added to the linear prediction with coefficient equal to 1.
    exposure : array_like
        Log(exposure) is added to the linear prediction with coefficient
        equal to 1.

    """ + base._missing_param_doc}

    def __init__(self, endog, exog, offset=None, exposure=None,
                 missing='none', **kwargs):
        self.zero_idx = np.nonzero(endog == 0)[0]
        self.nonzero_idx = np.nonzero(endog)[0]
        super(GenericCensored, self).__init__(
            endog,
            exog,
            offset=offset,
            exposure=exposure,
            missing=missing,
            **kwargs
            )

    def loglike(self, params):
        """
        Loglikelihood of Generic Censored model

        Parameters
        ----------
        params : array-like
            The parameters of the model.

        Returns
        -------
        loglike : float
            The log-likelihood function of the model evaluated at `params`.
            See notes.

        Notes
        --------

        """
        return np.sum(self.loglikeobs(params))

    def loglikeobs(self, params):
        """
        Loglikelihood for observations of Generic Censored model

        Parameters
        ----------
        params : array-like
            The parameters of the model.

        Returns
        -------
        loglike : ndarray (nobs,)
            The log likelihood for each observation of the model evaluated
            at `params`. See Notes

        Notes
        --------

        """
        llf_main = self.model_main.loglikeobs(params)

        llf = np.concatenate(
            (llf_main[self.zero_idx],
             np.log(1 - np.exp(llf_main[self.nonzero_idx])))
            )

        return llf

    def score_obs(self, params):
        """
        Generic Censored model score (gradient) vector of the log-likelihood

        Parameters
        ----------
        params : array-like
            The parameters of the model

        Returns
        -------
        score : ndarray, 1-D
            The score vector of the model, i.e. the first derivative of the
            loglikelihood function, evaluated at `params`
        """
        score_main = self.model_main.score_obs(params)
        llf_main = self.model_main.loglikeobs(params)

        score = np.concatenate((
            score_main[self.zero_idx],
            (score_main[self.nonzero_idx].T *
             -np.exp(llf_main[self.nonzero_idx]) /
             (1 - np.exp(llf_main[self.nonzero_idx]))).T
            ))

        return score

    def score(self, params):
        """
        Generic Censored model score (gradient) vector of the log-likelihood

        Parameters
        ----------
        params : array-like
            The parameters of the model

        Returns
        -------
        score : ndarray, 1-D
            The score vector of the model, i.e. the first derivative of the
            loglikelihood function, evaluated at `params`
        """
        return self.score_obs(params).sum(0)

    def fit(self, start_params=None, method='bfgs', maxiter=35,
            full_output=1, disp=1, callback=None,
            cov_type='nonrobust', cov_kwds=None, use_t=None, **kwargs):
        if start_params is None:
            offset = getattr(self, "offset", 0) + getattr(self, "exposure", 0)
            if np.size(offset) == 1 and offset == 0:
                offset = None
            model = self.model_main.__class__(self.endog, self.exog,
                                              offset=offset)
            start_params = model.fit(disp=0).params
        mlefit = super(GenericCensored, self).fit(
            start_params=start_params,
            maxiter=maxiter,
            disp=disp,
            full_output=full_output,
            callback=lambda x: x,
            **kwargs
            )

        zipfit = self.result(self, mlefit._results)
        result = self.result_wrapper(zipfit)

        if cov_kwds is None:
            cov_kwds = {}

        result._get_robustcov_results(cov_type=cov_type,
                                      use_self=True, use_t=use_t, **cov_kwds)
        return result

    fit.__doc__ = DiscreteModel.fit.__doc__

    def fit_regularized(
            self, start_params=None, method='l1',
            maxiter='defined_by_method', full_output=1, disp=1, callback=None,
            alpha=0, trim_mode='auto', auto_trim_tol=0.01, size_trim_tol=1e-4,
            qc_tol=0.03, **kwargs):

        if np.size(alpha) == 1 and alpha != 0:
            k_params = self.exog.shape[1]
            alpha = alpha * np.ones(k_params)

        alpha_p = alpha
        if start_params is None:
            offset = getattr(self, "offset", 0) + getattr(self, "exposure", 0)
            if np.size(offset) == 1 and offset == 0:
                offset = None
            model = self.model_main.__class__(self.endog, self.exog,
                                              offset=offset)
            start_params = model.fit_regularized(
                start_params=start_params, method=method, maxiter=maxiter,
                full_output=full_output, disp=0, callback=callback,
                alpha=alpha_p, trim_mode=trim_mode,
                auto_trim_tol=auto_trim_tol,
                size_trim_tol=size_trim_tol, qc_tol=qc_tol, **kwargs).params
        cntfit = super(CountModel, self).fit_regularized(
                start_params=start_params, method=method, maxiter=maxiter,
                full_output=full_output, disp=disp, callback=callback,
                alpha=alpha, trim_mode=trim_mode, auto_trim_tol=auto_trim_tol,
                size_trim_tol=size_trim_tol, qc_tol=qc_tol, **kwargs)

        if method in ['l1', 'l1_cvxopt_cp']:
            discretefit = self.result_reg(self, cntfit)
        else:
            raise TypeError(
                    "argument method == %s, which is not handled" % method)

        return self.result_reg_wrapper(discretefit)

    fit_regularized.__doc__ = DiscreteModel.fit_regularized.__doc__

    def hessian(self, params):
        """
        Generic Censored model Hessian matrix of the loglikelihood

        Parameters
        ----------
        params : array-like
            The parameters of the model

        Returns
        -------
        hess : ndarray, (k_vars, k_vars)
            The Hessian, second derivative of loglikelihood function,
            evaluated at `params`

        Notes
        -----
        """
        return approx_hess(params, self.loglike)


class CensoredPoisson(GenericCensored):
    """
    Censored Poisson model for count data

    %(params)s
    %(extra_params)s

    Attributes
    -----------
    endog : array
        A reference to the endogenous response variable
    exog : array
        A reference to the exogenous design.
    """ % {'params': base._model_params_doc,
           'extra_params':
           """offset : array_like
        Offset is added to the linear prediction with coefficient equal to 1.
    exposure : array_like
        Log(exposure) is added to the linear prediction with coefficient
        equal to 1.

    """ + base._missing_param_doc}

    def __init__(self, endog, exog, offset=None,
                 exposure=None, missing='none', **kwargs):
        super(CensoredPoisson, self).__init__(endog, exog, offset=offset,
                                              exposure=exposure,
                                              missing=missing, **kwargs)
        self.model_main = Poisson(np.zeros_like(self.endog), self.exog)
        self.model_dist = None
        self.result = GenericTruncatedResults
        self.result_wrapper = GenericTruncatedResultsWrapper
        self.result_reg = L1GenericTruncatedResults
        self.result_reg_wrapper = L1GenericTruncatedResultsWrapper


class CensoredGeneralizedPoisson(GenericCensored):
    """
    Censored Generalized Poisson model for count data

    %(params)s
    %(extra_params)s

    Attributes
    -----------
    endog : array
        A reference to the endogenous response variable
    exog : array
        A reference to the exogenous design.
    """ % {'params': base._model_params_doc,
           'extra_params':
           """offset : array_like
        Offset is added to the linear prediction with coefficient equal to 1.
    exposure : array_like
        Log(exposure) is added to the linear prediction with coefficient
        equal to 1.

    """ + base._missing_param_doc}

    def __init__(self, endog, exog, offset=None, p=2,
                 exposure=None, missing='none', **kwargs):
        super(CensoredGeneralizedPoisson, self).__init__(
            endog, exog, offset=offset, exposure=exposure,
            missing=missing, **kwargs)

        self.model_main = GeneralizedPoisson(
            np.zeros_like(self.endog), self.exog)
        self.model_dist = None
        self.result = GenericTruncatedResults
        self.result_wrapper = GenericTruncatedResultsWrapper
        self.result_reg = L1GenericTruncatedResults
        self.result_reg_wrapper = L1GenericTruncatedResultsWrapper


class CensoredNegativeBinomialP(GenericCensored):
    """
    Censored Negative Binomial model for count data

    %(params)s
    %(extra_params)s

    Attributes
    -----------
    endog : array
        A reference to the endogenous response variable
    exog : array
        A reference to the exogenous design.
    """ % {'params': base._model_params_doc,
           'extra_params':
           """offset : array_like
        Offset is added to the linear prediction with coefficient equal to 1.
    exposure : array_like
        Log(exposure) is added to the linear prediction with coefficient
        equal to 1.

    """ + base._missing_param_doc}

    def __init__(self, endog, exog, offset=None, p=2,
                 exposure=None, missing='none', **kwargs):
        super(CensoredNegativeBinomialP, self).__init__(
            endog,
            exog,
            offset=offset,
            exposure=exposure,
            missing=missing,
            **kwargs
            )
        self.model_main = NegativeBinomialP(np.zeros_like(self.endog),
                                            self.exog,
                                            p=p
                                            )
        self.model_dist = None
        self.result = GenericTruncatedResults
        self.result_wrapper = GenericTruncatedResultsWrapper
        self.result_reg = L1GenericTruncatedResults
        self.result_reg_wrapper = L1GenericTruncatedResultsWrapper


class Censored(GenericCensored):
    """
    Censored model for count data

    %(params)s
    %(extra_params)s

    Attributes
    -----------
    endog : array
        A reference to the endogenous response variable
    exog : array
        A reference to the exogenous design.
    """ % {'params': base._model_params_doc,
           'extra_params':
           """offset : array_like
        Offset is added to the linear prediction with coefficient equal to 1.
    exposure : array_like
        Log(exposure) is added to the linear prediction with coefficient
        equal to 1.

    """ + base._missing_param_doc}

    def __init__(self, endog, exog, model=Poisson,
                 distribution=truncatedpoisson, offset=None,
                 exposure=None, missing='none', **kwargs):
        super(Censored, self).__init__(
            endog,
            exog,
            offset=offset,
            exposure=exposure,
            missing=missing,
            **kwargs
            )
        self.model_main = model(np.zeros_like(self.endog), self.exog)
        self.model_dist = distribution
        self.result = GenericTruncatedResults
        self.result_wrapper = GenericTruncatedResultsWrapper
        self.result_reg = L1GenericTruncatedResults
        self.result_reg_wrapper = L1GenericTruncatedResultsWrapper

    def _prob_nonzero(self, mu, params):
        """Probability that count is not zero

        internal use in Censored model, will be refactored or removed
        """
        prob_nz = self.model_main._prob_nonzero(mu, params)
        return prob_nz


class Hurdle(CountModel):
    """
    Hurdle model for count data

    %(params)s
    %(extra_params)s

    Attributes
    -----------
    endog : array
        A reference to the endogenous response variable
    exog : array
        A reference to the exogenous design.
    dist : string
        Log-likelihood type of count model family. 'poisson' or 'negbin'
    zerodist : string
        Log-likelihood type of zero hurdle model family. 'poisson', 'negbin'
    p : scalar
        Define parameterization for count model.
        Used when dist='negbin'.
    pzero : scalar
        Define parameterization parameter zero hurdle model family.
        Used when zerodist='negbin'.
    """ % {'params': base._model_params_doc,
           'extra_params':
           """offset : array_like
        Offset is added to the linear prediction with coefficient equal to 1.
    exposure : array_like
        Log(exposure) is added to the linear prediction with coefficient
        equal to 1.

    """ + base._missing_param_doc}

    def __init__(self, endog, exog, offset=None,
                 dist="poisson", zerodist="poisson",
                 p=2, pzero=2,
                 exposure=None, missing='none', **kwargs):
        super(Hurdle, self).__init__(
            endog,
            exog,
            offset=offset,
            exposure=exposure,
            missing=missing,
            **kwargs
            )
        self.exog_names.insert(0, 'inflate_const')
        self.k_extra1 = 0
        self.k_extra2 = 0
        for i in range(self.exog.shape[1], 1, -1):
            self.exog_names.insert(0, 'zero_x%d' % (i-1))

        self._initialize(dist, zerodist, p, pzero)
        self.result = HurdleResults
        self.result_wrapper = HurdleResultsWrapper
        self.result_reg = L1HurdleResults
        self.result_reg_wrapper = L1HurdleResultsWrapper

    def _initialize(self, dist, zerodist, p, pzero):
        if (dist not in ["poisson", "negbin"] or
                zerodist not in ["poisson", "negbin"]):
            raise NotImplementedError('dist and zerodist must be "poisson",'
                                      '"negbin"')

        if zerodist == "poisson":
            self.model1 = Censored(self.endog, self.exog, model=Poisson)
        elif zerodist == "negbin":
            self.model1 = Censored(self.endog, self.exog,
                                   model=NegativeBinomialP)

        if dist == "poisson":
            self.model2 = TruncatedPoisson(self.endog, self.exog)
        elif dist == "negbin":
            self.model2 = TruncatedNegativeBinomialP(self.endog, self.exog,
                                                     p=p)

    def loglike(self, params):
        """
        Loglikelihood of Generic Hurdle model

        Parameters
        ----------
        params : array-like
            The parameters of the model.

        Returns
        -------
        loglike : float
            The log-likelihood function of the model evaluated at `params`.
            See notes.

        Notes
        --------

        """
        k = int((len(params) - self.k_extra1 - self.k_extra2) / 2
                ) + self.k_extra1
        return (self.model1.loglike(params[:k]) +
                self.model2.loglike(params[k:]))

    def fit(self, start_params=None, method='bfgs', maxiter=35,
            full_output=1, disp=1, callback=None,
            cov_type='nonrobust', cov_kwds=None, use_t=None, **kwargs):

        results1 = self.model1.fit(
            start_params=start_params,
            method=method, maxiter=maxiter, disp=disp,
            full_output=full_output, callback=lambda x: x,
            **kwargs
            )

        results2 = self.model2.fit(
            start_params=start_params,
            method=method, maxiter=maxiter, disp=disp,
            full_output=full_output, callback=lambda x: x,
            **kwargs
            )

        result = deepcopy(results1)
        result._results.model = self
        result.mle_retvals['converged'] = [results1.mle_retvals['converged'],
                                           results2.mle_retvals['converged']]
        result._results.params = np.append(results1._results.params,
                                           results2._results.params)
        # TODO: the following should be in __init__ or initialize
        result._results.df_model += results2._results.df_model
        self.k_extra1 += getattr(results1._results, "k_extra", 0)
        self.k_extra2 += getattr(results2._results, "k_extra", 0)
        self.k_extra = (self.k_extra1 + self.k_extra2 + 1)

        # fix up cov_params
        from scipy.linalg import block_diag
        result._results.normalized_cov_params = (
            block_diag(results1._results.cov_params(),
                       results2._results.cov_params()))

        modelfit = self.result(self, result._results, results1, results2)
        result = self.result_wrapper(modelfit)

        if cov_kwds is None:
            cov_kwds = {}

        result._get_robustcov_results(cov_type=cov_type,
                                      use_self=True, use_t=use_t, **cov_kwds)
        return result

    fit.__doc__ = DiscreteModel.fit.__doc__

    def predict(self, params, exog=None, exog_zero=None, exposure=None,
                offset=None, which='mean', y_values=None):
        """
        Predict response variable or other statistic given exogenous variables.

        Parameters
        ----------
        params : array_like
            The parameters of the model.
        exog : ndarray, optional
            Explanatory variables for the main count model.
            If ``exog`` is None, then the data from the model will be used.
        exog_infl : ndarray, optional
            Explanatory variables for the zero-inflation model.
            ``exog_infl`` has to be provided if ``exog`` was provided unless
            ``exog_infl`` in the model is only a constant.
        offset : ndarray, optional
            Offset is added to the linear predictor of the mean function with
            coefficient equal to 1.
            Default is zero if exog is not None, and the model offset if exog
            is None.
        exposure : ndarray, optional
            Log(exposure) is added to the linear predictor with coefficient
            equal to 1. If exposure is specified, then it will be logged by
            the method. The user does not need to log it first.
            Default is one if exog is is not None, and it is the model exposure
            if exog is None.
        which : str (optional)
            Statitistic to predict. Default is 'mean'.

            - 'mean' : the conditional expectation of endog E(y | x),
              i.e. exp of linear predictor.
            - 'linear' : the linear predictor of the mean function.
            - 'var' : returns the estimated variance of endog implied by the
              model.
            - 'mean-main' : untruncated mean of the main count model
            - 'prob-main' : probability of selecting the main model.
                The probability of zero inflation is ``1 - prob-main``.
            - 'mean-nonzero' : expected value conditional on having observation
              larger than zero, E(y | X, y>0)
            - 'prob-zero' : probability of observing a zero count. P(y=0 | x)
            - 'prob' : probabilities of each count from 0 to max(endog), or
              for y_values if those are provided. This is a multivariate
              return (2-dim when predicting for several observations).

        y_values : array_like
            Values of the random variable endog at which pmf is evaluated.
            Only used if ``which="prob"``
        """
        which = which.lower()  # make it case insensitive
        no_exog = True if exog is None else False
        exog, offset, exposure = self._get_predict_arrays(
            exog=exog,
            offset=offset,
            exposure=exposure
            )

        if exog_zero is None:
            if no_exog:
                exog_zero = self.exog
            else:
                exog_zero = exog

        k_zeros = int((len(params) - self.k_extra1 - self.k_extra2) / 2
                      ) + self.k_extra1
        params_zero = params[:k_zeros]
        params_main = params[k_zeros:]

        lin_pred = (np.dot(exog, params_main[:self.exog.shape[1]]) +
                    exposure + offset)

        # this currently is mean_main, offset, exposure for zero part ?
        mu1 = self.model1.predict(params_zero, exog=exog)
        prob_main = self.model1.model_main._prob_nonzero(mu1, params_zero)
        prob_zero = (1 - prob_main)

        mu2 = np.exp(lin_pred)
        prob_ntrunc = self.model1.model_main._prob_nonzero(mu2, params_main)

        if which == 'mean':
            return prob_main * np.exp(lin_pred) / prob_ntrunc
        elif which == 'mean-main':
            return np.exp(lin_pred)
        elif which == 'linear':
            return lin_pred
        elif which == 'mean-nonzero':
            return np.exp(lin_pred) / prob_ntrunc
        elif which == 'prob-zero':
            return prob_zero
        elif which == 'prob-main':
            return prob_main
        elif which == 'prob-trunc':
            return 1 - prob_ntrunc
        # not yet supported
        # elif which == 'var':
        #     mu = np.exp(lin_pred)
        #     return self._predict_var(params, mu, 1 - prob_main)
        elif which == 'prob':
            probs_main = self.model2.predict(
                params_main, exog, np.exp(exposure), offset, which="prob",
                count_prob=y_values)
            probs_main *= prob_main[:, None]
            probs_main[:, 0] = prob_zero
            return probs_main
        else:
            raise ValueError('which = %s is not available' % which)


class GenericTruncatedResults(CountResults):
    __doc__ = _discrete_results_docs % {
        "one_line_description": "A results class for Generic Truncated",
        "extra_attr": ""}


class TruncatedPoissonResults(GenericTruncatedResults):
    __doc__ = _discrete_results_docs % {
        "one_line_description": "A results class for Truncated Poisson",
        "extra_attr": ""}

    @cache_readonly
    def _dispersion_factor(self):
        if self.model.trunc != 0:
            msg = "dispersion is only available for zero-truncation"
            raise NotImplementedError(msg)

        mu = np.exp(self.predict(which='linear'))

        return (1 - mu / (np.exp(mu) - 1))


class TruncatedNegativeBinomialResults(GenericTruncatedResults):
    __doc__ = _discrete_results_docs % {
        "one_line_description":
            "A results class for Truncated Negative Binomial",
        "extra_attr": ""}

    @cache_readonly
    def _dispersion_factor(self):
        if self.model.trunc != 0:
            msg = "dispersion is only available for zero-truncation"
            raise NotImplementedError(msg)

        alpha = self.params[-1]
        p = self.model.model_main.parameterization
        mu = np.exp(self.predict(which='linear'))

        return (1 - alpha * mu**(p-1) / (np.exp(mu**(p-1)) - 1))


class L1GenericTruncatedResults(L1CountResults, GenericTruncatedResults):
    pass


class GenericTruncatedResultsWrapper(lm.RegressionResultsWrapper):
    pass


wrap.populate_wrapper(GenericTruncatedResultsWrapper,
                      GenericTruncatedResults)


class L1GenericTruncatedResultsWrapper(lm.RegressionResultsWrapper):
    pass


wrap.populate_wrapper(L1GenericTruncatedResultsWrapper,
                      L1GenericTruncatedResults)


class HurdleResults(CountResults):
    __doc__ = _discrete_results_docs % {
        "one_line_description": "A results class for Hurdle model",
        "extra_attr": ""}

    def __init__(self, model, mlefit, model1, model2, cov_type='nonrobust',
                 cov_kwds=None, use_t=None):
        super(HurdleResults, self).__init__(
            model,
            mlefit,
            cov_type=cov_type,
            cov_kwds=cov_kwds,
            use_t=use_t,
            )
        self.model1 = model1
        self.model2 = model2
        # TODO: this is to fix df_resid, should be automatic but is not
        self.df_resid = self.model.endog.shape[0] - len(self.params)

    @cache_readonly
    def llnull(self):
        return self.model1._results.llnull + self.model2._results.llnull

    @cache_readonly
    def bse(self):
        return np.append(self.model1.bse, self.model2.bse)


class L1HurdleResults(L1CountResults, HurdleResults):
    pass


class HurdleResultsWrapper(lm.RegressionResultsWrapper):
    pass


wrap.populate_wrapper(HurdleResultsWrapper,
                      HurdleResults)


class L1HurdleResultsWrapper(lm.RegressionResultsWrapper):
    pass


wrap.populate_wrapper(L1HurdleResultsWrapper,
                      L1HurdleResults)
