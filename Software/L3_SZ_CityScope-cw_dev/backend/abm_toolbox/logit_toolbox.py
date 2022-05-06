import pandas as pd
import time
import numpy as np
from sklearn.metrics import confusion_matrix, accuracy_score, f1_score
import pylogit as pl
from collections import OrderedDict


def long_form_data(mode_table, alt_attrs, generic_attrs, modes, y_true=True):
    """
    generate long form data for logit model from mode table

    Arguments:
    ---------------------------------
    mode_table: pandas dataframe with mocho information
    alt_attrs: alternative-specific attributes, dict: key=varname in long form dataframe,
               value=varname for each alternative in mode_table
    generic_attrs: case-specific attributes, generally demographic vars, list, ele=varname in mode_table.
    modes: a list of mode names

    Returns:
    -----------------------------------
    long_data_df: pandas dataframe in logit long data form
    """
    nalt = len(modes)
    basic_columns = ['group', 'alt', 'choice']
    alt_tmp, choice_tmp = modes, [0 for i in range(nalt)]
    keys = basic_columns + list(alt_attrs.keys()) + generic_attrs
    long_data_obj = {key: [] for key in keys}
    for rid, row in mode_table.iterrows():
        long_data_obj['group'] += [rid for i in range(nalt)]
        long_data_obj['alt'] += alt_tmp
        mode_choice = choice_tmp.copy()
        if y_true:
            mode_choice[modes.index(row['mode'])] = 1
        long_data_obj['choice'] += mode_choice
        for alt_attr in alt_attrs:
            long_data_obj[alt_attr] += [row.get(row_attr, 0) for row_attr in alt_attrs[alt_attr]]
        for g_attr in generic_attrs:
            long_data_obj[g_attr] += [row[g_attr] for i in range(nalt)]
    long_data_df = pd.DataFrame.from_dict(long_data_obj)
    return long_data_df


def long_form_data_upsample(long_data_df_in, upsample_new={0: '+0', 1: '+0', 2: '+0', 3: '+0'},
                            seed=None, disp=True):
    """
    make the long_form_data more balanced by upsampling
    (add randomly sampled new cases less represented alternatives)

    Arguments:
    ---------------------------------
    long_data_df_in: input long form dataframe
    upsample_new: a dict defining how many new cases are added for each alternative,
                  key: index of alternaive
                  value: "+N" to add N cases or "*N" to increase the number of cases by N times.
    seed: random seed

    Returns:
    -----------------------------------
    long_data_df_out: output long form dataframe after upsampling
    """
    print('upsampling...')
    long_data_df_out = long_data_df_in.copy()
    casedata_list = [data for caseID, data in long_data_df_out.copy().groupby('group')]
    caseIDs = list(set(long_data_df_out['group']))
    # alt_spec_casedata_list = dict()
    dist_before, dist_after = [], []
    new_casedata_list = []
    if seed is not None:
        np.random.seed(seed)
    for alt_idx in upsample_new:
        this_alt_casedata_list = [data for data in casedata_list if list(data['choice'])[alt_idx] == 1]
        num_this_alt_casedata = len(this_alt_casedata_list)
        dist_before.append('{}-{}'.format(alt_idx, num_this_alt_casedata))
        if upsample_new[alt_idx].startswith('+'):
            num_new = int(upsample_new[alt_idx][1:])
        elif upsample_new[alt_idx].startswith('*'):
            num_new = int(num_this_alt_casedata * (float(upsample_new[alt_idx][1:]) - 1))
        # alt_spec_casedata_list[alt_idx] = this_alt_casedata_list
        new_casedata_list += [this_alt_casedata_list[i].copy() for i in np.random.choice(
            range(len(this_alt_casedata_list)), size=num_new)]
        dist_after.append('{}-{}'.format(alt_idx, num_this_alt_casedata + num_new))
    maxID = np.array(caseIDs).max()
    for idx, new_casedata in enumerate(new_casedata_list):
        new_casedata['group'] = maxID + idx + 1
    long_data_df_out = pd.concat([long_data_df_out] + new_casedata_list, axis=0)
    if disp:
        print('Before: {}'.format(', '.join(dist_before)))
        print('After: {}'.format(', '.join(dist_after)))

    return long_data_df_out


def logit_spec(long_data_df, alt_attr_vars, generic_attrs=[], constant=True,
               alts={0: 'drive', 1: 'cycle', 2: 'walk', 3: 'PT'}, ref_alt_idx=0):
    """
    generate specification & varnames for pylogit

    Arguments:
    ------------------------------
    long_data_df: pandas dataframe, long data, generated by long_form_data
    alt_attr_vars: list of alternative specific vars
    generic_attrs: list of case specific vars, generally demographic vars
    constant: whether or not to include ASCs
    alts: a dict or list to define indices and names of alternative
    ref_alt_idx: index of reference alternative for ASC specification

    Returns:
    --------------------------------
    model: pylogit MNL model object
    numCoef: the number of coefficients to estimated
    """
    specifications = OrderedDict()
    names = OrderedDict()
    nalt = len(alts)
    if isinstance(alts, list):
        alts = {i: alts[i] for i in range(nalt)}
    for var in alt_attr_vars:
        # specifications[var] = [list(range(nalt))]
        specifications[var] = [list(alts.values())]
        names[var] = [var]
    for var in generic_attrs:
        # specifications[var] = [i for i in range(nalt) if i != ref_alt_idx]
        specifications[var] = [alts[i] for i in range(nalt) if i != ref_alt_idx]
        names[var] = [var + ' for ' + alts[i] for i in range(nalt) if i != ref_alt_idx]
    if constant:
        # specifications['intercept'] = [i for i in range(nalt) if i != ref_alt_idx]
        specifications['intercept'] = [alts[i] for i in range(nalt) if i != ref_alt_idx]
        names['intercept'] = ['ASC for ' + alts[i] for i in range(nalt) if i != ref_alt_idx]
    model = pl.create_choice_model(data=long_data_df.copy(),
                                   alt_id_col="alt",
                                   obs_id_col="group",
                                   choice_col="choice",
                                   specification=specifications,
                                   model_type="MNL",
                                   names=names
                                   )
    numCoef = sum([len(specifications[s]) for s in specifications])
    return model, numCoef


def logit_est_disp(model, numCoef, nalt=4, disp=True):
    """
    estimate a logit model and display results, using just_point=True in case of memory error

    Arguments:
    ---------------------------
    model & numCoef: see logit_spec; nalt: the number of alternatives
    disp: whether or not to display estimation results.

    Return:
    ----------------------------
    modelDict: a dict, "just_point" indicates whether the model is point-estimate only (no std.err / ttest / p-value)
                       "model" is the pylogit MNL model object, it is better used when just_point=False
                       "params": a dict with key=varible_name and value=parameter, only valid for just_point=True
    """
    try:
        model.fit_mle(np.zeros(numCoef))
        if disp:
            print(model.get_statsmodels_summary())
        params = {}
        for param, varname in zip(model.coefs.values, model.coefs.index):
            params[varname] = param
        return {'just_point': False, 'params': params, 'model': model}
    except:
        model_result = model.fit_mle(np.zeros(numCoef), just_point=True)
        ncs = int(model.data.shape[0] / nalt)
        beta = model_result['x']
        if disp:
            ll0 = np.log(1 / nalt) * ncs
            ll = -model_result['fun']
            mcr = 1 - ll / ll0
            print('\n\nLogit model summary\n---------------------------')
            print('number of cases: ', ncs)
            print('Initial Log-likelihood: ', ll0)
            print('Final Log-likelihood: ', ll)
            print('McFadden R2: {:4.4}\n'.format(mcr))
            print('\nLogit model parameters:\n---------------------------')
            for varname, para in zip(model.ind_var_names, beta):
                print('{}: {:4.6f}'.format(varname, para))
        params = {varname: param for varname, param in zip(model.ind_var_names, beta)}
        return {'just_point': True, 'params': params, 'model': model}


def logit_cv(data, alt_attr_vars, generic_attrs, constant=True, nfold=5, seed=None,
             alts={0: 'drive', 1: 'cycle', 2: 'walk', 3: 'PT'},
             upsample_new={0: '+0', 1: '+0', 2: '+0', 3: '+0'},
             method='max'
             ):
    """
    cross validation for logit model performance

    Arguments:
    ---------------------------
    data: input long form pandas dataframe
    alt_attr_vars, generic_attrs, constant, alts: logit model specification, see logit_spec
    nfold: number of folds in cv; seed: random seed for np.random
    upsample_new: upsampling specification for unbalanced data, see long_form_data_upsample
    method:

    Return:
    ----------------------------
    cv_metrics: a dict with average accuracy and F1 macro score
    cv_metrics_detail: a dict with accuracy and F1 macro score  for each fold
    """
    long_data_df = data.copy()
    if seed is not None:
        np.random.seed(seed)
    caseIDs = list(set(long_data_df['group']))
    np.random.shuffle(caseIDs)
    ncs = len(caseIDs)
    nsampe_fold = int(ncs / nfold)
    cv_data = {i: long_data_df.loc[long_data_df['group'].isin(
        caseIDs[i * nsampe_fold: (i + 1) * nsampe_fold])].copy() for i in range(nfold)}
    cv_metrics_detail = {i: {'accuracy': None, 'f1_macro': None} for i in range(nfold)}
    accuracy_list, f1_macro_list = [], []
    for holdout_idx in cv_data:
        print('\ncv for fold=', holdout_idx)
        long_data_df_test = cv_data[holdout_idx].copy()
        train_list = [d.copy() for idx, d in cv_data.items() if idx != holdout_idx]
        long_data_df_train = pd.concat(train_list, axis=0).sort_values(by=['group', 'alt'])
        long_data_df_train = long_form_data_upsample(long_data_df_train, upsample_new=upsample_new, seed=seed)
        model_train, numCoefs = logit_spec(long_data_df_train, alt_attr_vars, generic_attrs, constant=constant,
                                           alts=alts)
        modelDict_train = logit_est_disp(model_train, numCoefs, nalt=len(alts), disp=False)
        pred_prob_test, y_pred_test = asclogit_pred(long_data_df_test, modelDict_train,
                                                    customIDColumnName='group', alts=alts, method=method, seed=seed)
        y_true_test = np.array(long_data_df_test['choice']).reshape(-1, len(alts)).argmax(axis=1)
        ac, f1 = accuracy_score(y_true_test, y_pred_test), f1_score(y_true_test, y_pred_test, average='macro')
        cv_metrics_detail[holdout_idx]['accuracy'] = ac
        accuracy_list.append(ac)
        cv_metrics_detail[holdout_idx]['f1_macro'] = f1
        f1_macro_list.append(f1)
        print(confusion_matrix(y_true_test, y_pred_test))
    cv_metrics = {'accuracy': np.asarray(accuracy_list).mean(),
                  'f1_macro': np.asarray(f1_macro_list).mean()}
    print('cv finished\n')
    return cv_metrics, cv_metrics_detail


def asclogit_pred(data_in, modelDict, customIDColumnName, method='random', seed=None,
                  alts={0: 'drive', 1: 'cycle', 2: 'walk', 3: 'PT'}):
    """
    predict probabilities for logit model

    Arguments:
    -------------------------------
    data_in: pandas dataframe to be predicted
    modelDict: see logit_est_disp
    customIDColumnName: the column name of customer(case) ID
    alts: a dict or list defining the indices and name of altneratives

    Return:
    ----------------------------------
    a mat (num_cases * num_alts) of predicted probabilities, row sum=1
    """
    data = data_in.copy()
    numChoices = len(set(data[customIDColumnName]))
    # fectch variable names and parameters
    params, varnames = modelDict['params'].values(), modelDict['params'].keys()

    # case specific vars and alternative specific vars
    nalt = len(alts)
    if isinstance(alts, list):
        alts = {i: alts[i] for i in range(nalt)}
    dummies_dict = dict()
    case_varname_endswith_flag = []
    for alt_idx, alt_name in alts.items():
        case_varname_endswith_flag.append(' for ' + alt_name)
        tmp = [0 for i in range(nalt)]
        tmp[alt_idx] = 1
        dummies_dict[alt_name] = np.tile(np.asarray(tmp), numChoices)
    case_varname_endswith_flag = tuple(case_varname_endswith_flag)

    # calc utilities
    data['utility'] = 0
    for varname, param in zip(varnames, params):
        if not varname.endswith(case_varname_endswith_flag):
            # this is an alternative specific varname
            data['utility'] += data[varname] * param
        else:
            # this is a case specific varname (ASC-like)
            main_varname, interact_with_alt = varname.split(' for ')
            use_dummy = dummies_dict[interact_with_alt]
            if main_varname == 'ASC':
                data['utility'] += use_dummy * param
            elif main_varname in data.columns:
                data['utility'] += data[main_varname] * use_dummy * param
            else:
                print('Error: can not find variable: {}'.format(varname))
                return

    # calc probabilities given utilities
    v = np.array(data['utility']).copy().reshape(numChoices, -1)
    v_raw = v.copy()
    v = v - v.mean(axis=1, keepdims=True)
    v[v > 700] = 700
    v[v < -700] = -700
    expV = np.exp(v)
    p = expV / expV.sum(axis=1, keepdims=True)
    p = p.reshape(-1, nalt)
    if method == 'max':
        y = p.argmax(axis=1)
    elif method == 'random':
        if seed is not None:
            np.random.seed(seed)
        y = np.asarray([np.random.choice(list(alts.keys()), size=1, p=row)[0] for row in p])
    elif method == 'none':
        y = None
    return p, y, v_raw